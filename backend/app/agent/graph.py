"""LangGraph agent loop: plan -> tools -> answer (plan section 5).

The planner node (LLM via LiteLLM) decides which tools to call and may iterate
(query, inspect the result, query again) before drafting an answer. Once it has
the data it needs, it writes a grounded answer that references the real numbers
the tools returned, and the answer node packages the structured ``AgentAnswer``.

M3 wires the loop with two tools (``query_events``, ``shot_map``). The grounding
check that verifies every cited number against tool output is M5.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from .. import llm
from . import grounding, tools
from .schemas import AgentAnswer, CitedStat

logger = logging.getLogger(__name__)

# Max plan<->tools cycles before we force an answer (free-tier safety valve).
_MAX_TOOL_ITERATIONS = 4

_SYSTEM_PROMPT = (
    "You are Gaffer, a football analyst grounded in real StatsBomb event data "
    "from the FIFA World Cup 2022. Answer tactical and scouting questions in "
    "clear, concise prose.\n\n"
    "Tools — pick the one that matches the question:\n"
    "- `shot_map(player)` — a player's shooting, chances, xG, or finishing.\n"
    "- `query_events(filters)` — look up or count events (shots, passes, etc).\n"
    "- `pass_network(team, opponent|match_id)` — how a team built up in one "
    "match (e.g. 'France's pass network vs Argentina'). Always pass an opponent "
    "or match id along with the team.\n"
    "- `compare_players(player_a, player_b)` — radar comparison of two players' "
    "tournament metrics (shots, goals, xG, key passes, assists, progressive "
    "passes). Use for 'compare X and Y' or 'who was better at ...'.\n"
    "- `tactics_lookup(query)` — a tactical concept ('what is a low block?', "
    "'explain xG'). Returns short reference chunks; ground definitions in them.\n\n"
    "Rules:\n"
    "- ALWAYS obtain numbers from the tools; never invent or recall stats from "
    "memory. If you need a figure, call a tool.\n"
    "- Once you have the data you need, write the final answer directly (no more "
    "tool calls). Reference the real numbers the tools returned.\n"
    "- For a tactics_lookup answer, summarise the retrieved chunks in your own "
    "words and cite the source file (e.g. 'low_block.md').\n"
    "- Keep it to a few sentences. Be specific and analytical, not generic."
)


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    iterations: int
    draft: str
    verification: grounding.VerificationResult
    answer: AgentAnswer


# --- nodes ----------------------------------------------------------------


def plan_node(state: AgentState) -> AgentState:
    """Ask the LLM what to do next: call tool(s) or write the final answer."""
    messages = state["messages"]
    iterations = state.get("iterations", 0)

    # After the iteration budget, drop tools so the model must answer.
    use_tools = iterations < _MAX_TOOL_ITERATIONS
    msg = llm.chat(
        messages,
        tools=tools.TOOL_SPECS if use_tools else None,
        temperature=0.2,
    )

    assistant: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls:
        assistant["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments or "{}",
                },
            }
            for tc in tool_calls
        ]
    messages = messages + [assistant]
    return {"messages": messages, "draft": msg.content or "", "iterations": iterations}


def tools_node(state: AgentState) -> AgentState:
    """Execute every tool call from the last assistant message and append results."""
    messages = list(state["messages"])
    results = list(state.get("tool_results", []))
    last = messages[-1]

    for tc in last.get("tool_calls", []):
        name = tc["function"]["name"]
        try:
            args = json.loads(tc["function"]["arguments"] or "{}")
        except json.JSONDecodeError:
            args = {}
        result = tools.dispatch(name, args)
        results.append(result)
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tc["id"],
                "name": name,
                "content": json.dumps(_tool_content_for_llm(result)),
            }
        )

    return {
        "messages": messages,
        "tool_results": results,
        "iterations": state.get("iterations", 0) + 1,
    }


def verify_node(state: AgentState) -> AgentState:
    """M5 grounding gate: check every numeric claim in the draft against tool outputs.

    Runs the programmatic tolerance check first, then a cheap-LLM backstop, and
    rewrites the draft once if unsupported claims are found. The result carries
    a ``grounded`` flag and an audit trail into ``AgentAnswer``.
    """
    draft = state.get("draft", "") or ""
    result = grounding.verify(draft, state.get("tool_results", []))
    logger.info(
        "grounding: grounded=%s notes=%s unsupported=%s",
        result.grounded,
        result.notes,
        [u.get("token") for u in result.unsupported],
    )
    return {"verification": result, "draft": result.draft}


def answer_node(state: AgentState) -> AgentState:
    """Assemble the structured AgentAnswer from the (possibly rewritten) draft.

    Iterates over every tool result and asks the per-tool extractor what to
    surface in ``visuals``/``cited_stats``. Errored results are skipped. Image
    URLs are de-duplicated while preserving the order the tools ran in. The
    grounding audit trail from ``verify_node`` lands in ``grounded`` /
    ``verification_notes``.
    """
    results = state.get("tool_results", [])

    visuals: list[str] = []
    cited: list[CitedStat] = []
    seen_visuals: set[str] = set()
    for r in results:
        if r.get("error"):
            continue
        extractor = _EXTRACTORS.get(r.get("tool"))
        if extractor is None:
            continue
        v, c = extractor(r)
        for url in v:
            if url and url not in seen_visuals:
                seen_visuals.add(url)
                visuals.append(url)
        cited += c

    verification = state.get("verification")
    grounded = bool(verification.grounded) if verification else False
    notes = list(verification.notes) if verification else []
    if verification and verification.unsupported:
        notes.append(
            "unresolved claims: "
            + ", ".join(u.get("token", "?") for u in verification.unsupported)
        )

    answer = AgentAnswer(
        answer_text=state.get("draft", "").strip(),
        visuals=visuals,
        cited_stats=cited,
        grounded=grounded,
        verification_notes=notes,
    )
    return {"answer": answer}


# --- per-tool extractors --------------------------------------------------
# Each function turns one tool-result dict into (visuals_to_append, cited_stats).
# Keep them small and pure — answer_node does the de-duping and assembly.


def _extract_shot_map(r: dict[str, Any]) -> tuple[list[str], list[CitedStat]]:
    visuals = [r["image_url"]] if r.get("image_url") else []
    cited: list[CitedStat] = []
    stats = r.get("stats") or {}
    player = r.get("player", "player")
    if stats:
        cited += [
            CitedStat(label=f"{player} shots", value=str(stats["shots"]), source="shot_map"),
            CitedStat(label=f"{player} goals", value=str(stats["goals"]), source="shot_map"),
            CitedStat(label=f"{player} xG", value=f"{stats['xg']:.2f}", source="shot_map"),
        ]
    return visuals, cited


def _extract_query_events(r: dict[str, Any]) -> tuple[list[str], list[CitedStat]]:
    if "count" not in r:
        return [], []
    label = f"{r['resolved_player']} events" if r.get("resolved_player") else "matching events"
    return [], [CitedStat(label=label, value=str(r["count"]), source="query_events")]


def _extract_pass_network(r: dict[str, Any]) -> tuple[list[str], list[CitedStat]]:
    visuals = [r["image_url"]] if r.get("image_url") else []
    cited: list[CitedStat] = []
    team, opp = r.get("team"), r.get("opponent")
    if team and opp:
        match_label = f"{team} vs {opp}"
        cited.append(CitedStat(
            label=f"{match_label} completed passes",
            value=str(r.get("passes_completed", 0)),
            source="pass_network",
        ))
        top = (r.get("top_edges") or [])[:1]
        if top:
            t = top[0]
            cited.append(CitedStat(
                label=f"top pair: {t['a']} ↔ {t['b']}",
                value=str(t["passes"]),
                source="pass_network",
            ))
    return visuals, cited


def _extract_compare_players(r: dict[str, Any]) -> tuple[list[str], list[CitedStat]]:
    visuals = [r["image_url"]] if r.get("image_url") else []
    cited: list[CitedStat] = []
    a = r.get("player_a")
    b = r.get("player_b")
    if a and b:
        ma = r.get("metrics_a", {})
        mb = r.get("metrics_b", {})
        for key in r.get("metrics", []):
            if key not in ma or key not in mb:
                continue
            cited.append(CitedStat(
                label=f"{a} {key}",
                value=_fmt_metric(ma[key]),
                source="compare_players",
            ))
            cited.append(CitedStat(
                label=f"{b} {key}",
                value=_fmt_metric(mb[key]),
                source="compare_players",
            ))
    return visuals, cited


def _extract_tactics_lookup(r: dict[str, Any]) -> tuple[list[str], list[CitedStat]]:
    cited: list[CitedStat] = []
    for h in r.get("hits", [])[:3]:
        cited.append(CitedStat(
            label=f"tactics_kb: {h['source']}",
            value=f"score {h['score']:.2f}",
            source="tactics_lookup",
        ))
    return [], cited


def _fmt_metric(v: float | int) -> str:
    """Compact metric formatter: integers stay integers, decimals get 2dp."""
    fv = float(v)
    return str(int(fv)) if fv.is_integer() else f"{fv:.2f}"


_EXTRACTORS = {
    "shot_map": _extract_shot_map,
    "query_events": _extract_query_events,
    "pass_network": _extract_pass_network,
    "compare_players": _extract_compare_players,
    "tactics_lookup": _extract_tactics_lookup,
}


# --- routing --------------------------------------------------------------


def _after_plan(state: AgentState) -> str:
    """Route to tool execution when the planner asked for tools, else to the M5 verify gate."""
    last = state["messages"][-1]
    return "tools" if last.get("tool_calls") else "verify"


def _tool_content_for_llm(result: dict[str, Any]) -> dict[str, Any]:
    """Trim large arrays before feeding a tool result back to the model.

    Big tool payloads (per-shot markers, pass-network nodes/edges, RAG text)
    blow up the LLM context with little marginal benefit — the model only needs
    the headlines to write the answer.
    """
    trimmed = dict(result)
    shots = trimmed.get("shots")
    if isinstance(shots, list) and len(shots) > 25:
        trimmed["shots"] = shots[:25]
        trimmed["shots_truncated"] = f"showing 25 of {len(shots)}"
    # pass_network: drop full nodes list (we keep summary stats + top edges).
    if trimmed.get("tool") == "pass_network":
        nodes = trimmed.get("nodes")
        if isinstance(nodes, list) and len(nodes) > 0:
            trimmed["nodes_count"] = len(nodes)
            trimmed["nodes"] = [n["player"] for n in nodes]  # just names
        edges = trimmed.get("top_edges")
        if isinstance(edges, list) and len(edges) > 6:
            trimmed["top_edges"] = edges[:6]
    # tactics_lookup: keep the text (model needs to reason over it) but cap
    # length so a future longer note can't dominate the prompt.
    if trimmed.get("tool") == "tactics_lookup":
        capped: list[dict[str, Any]] = []
        for h in trimmed.get("hits", [])[:4]:
            text = h.get("text", "")
            capped.append({**h, "text": text[:900]})
        trimmed["hits"] = capped
    return trimmed


# --- graph assembly -------------------------------------------------------

_GRAPH = None


def build_graph():
    """Compile the plan -> tools -> verify -> answer state graph."""
    builder = StateGraph(AgentState)
    builder.add_node("plan", plan_node)
    builder.add_node("tools", tools_node)
    builder.add_node("verify", verify_node)
    builder.add_node("answer", answer_node)

    builder.set_entry_point("plan")
    builder.add_conditional_edges("plan", _after_plan, {"tools": "tools", "verify": "verify"})
    builder.add_edge("tools", "plan")
    builder.add_edge("verify", "answer")
    builder.add_edge("answer", END)
    return builder.compile()


def run(question: str, history: list[dict] | None = None) -> AgentAnswer:
    """Run the agent on a natural-language question and return the structured answer.

    ``history`` is an optional list of prior ``{role, content}`` message pairs
    (user and assistant turns) injected between the system prompt and the current
    question, giving the model conversational context. The /chat endpoint populates
    this from the in-memory session store.
    """
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()

    messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]
    if history:
        messages += history
    messages.append({"role": "user", "content": question})

    init: AgentState = {
        "messages": messages,
        "tool_results": [],
        "iterations": 0,
    }
    final = _GRAPH.invoke(init, config={"recursion_limit": 25})
    return final["answer"]
