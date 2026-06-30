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
from . import tools
from .schemas import AgentAnswer, CitedStat

logger = logging.getLogger(__name__)

# Max plan<->tools cycles before we force an answer (free-tier safety valve).
_MAX_TOOL_ITERATIONS = 4

_SYSTEM_PROMPT = (
    "You are Gaffer, a football analyst grounded in real StatsBomb event data "
    "from the FIFA World Cup 2022. Answer tactical and scouting questions in "
    "clear, concise prose.\n\n"
    "Rules:\n"
    "- ALWAYS obtain numbers from the tools; never invent or recall stats from "
    "memory. If you need a figure, call a tool.\n"
    "- Use `shot_map` for anything about a player's shooting, chances, xG, or "
    "finishing. Use `query_events` to look up or count events.\n"
    "- Once you have the data you need, write the final answer directly (no more "
    "tool calls). Reference the key numbers (shots, goals, xG) explicitly.\n"
    "- Keep it to a few sentences. Be specific and analytical, not generic."
)


class AgentState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    iterations: int
    draft: str
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


def answer_node(state: AgentState) -> AgentState:
    """Assemble the structured AgentAnswer from the draft + tool outputs."""
    results = state.get("tool_results", [])

    visuals: list[str] = []
    cited: list[CitedStat] = []

    shot_result = next(
        (
            r
            for r in reversed(results)
            if r.get("tool") == "shot_map" and not r.get("error")
        ),
        None,
    )
    if shot_result:
        s = shot_result.get("stats") or {}
        player = shot_result.get("player", "player")
        if s:
            cited += [
                CitedStat(label=f"{player} shots", value=str(s["shots"]), source="shot_map"),
                CitedStat(label=f"{player} goals", value=str(s["goals"]), source="shot_map"),
                CitedStat(label=f"{player} xG", value=f"{s['xg']:.2f}", source="shot_map"),
            ]
        if shot_result.get("image_url"):
            visuals.append(shot_result["image_url"])

    for r in results:
        if r.get("tool") == "query_events" and "count" in r and not r.get("error"):
            label = "matching events"
            if r.get("resolved_player"):
                label = f"{r['resolved_player']} events"
            cited.append(
                CitedStat(label=label, value=str(r["count"]), source="query_events")
            )

    answer = AgentAnswer(
        answer_text=state.get("draft", "").strip(),
        visuals=visuals,
        cited_stats=cited,
    )
    return {"answer": answer}


# --- routing --------------------------------------------------------------


def _after_plan(state: AgentState) -> str:
    last = state["messages"][-1]
    return "tools" if last.get("tool_calls") else "answer"


def _tool_content_for_llm(result: dict[str, Any]) -> dict[str, Any]:
    """Trim large arrays before feeding a tool result back to the model."""
    trimmed = dict(result)
    shots = trimmed.get("shots")
    if isinstance(shots, list) and len(shots) > 25:
        trimmed["shots"] = shots[:25]
        trimmed["shots_truncated"] = f"showing 25 of {len(shots)}"
    return trimmed


# --- graph assembly -------------------------------------------------------

_GRAPH = None


def build_graph():
    """Compile the plan -> tools -> answer state graph."""
    builder = StateGraph(AgentState)
    builder.add_node("plan", plan_node)
    builder.add_node("tools", tools_node)
    builder.add_node("answer", answer_node)

    builder.set_entry_point("plan")
    builder.add_conditional_edges("plan", _after_plan, {"tools": "tools", "answer": "answer"})
    builder.add_edge("tools", "plan")
    builder.add_edge("answer", END)
    return builder.compile()


def run(question: str) -> AgentAnswer:
    """Run the agent on a natural-language question and return the structured answer."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()

    init: AgentState = {
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ],
        "tool_results": [],
        "iterations": 0,
    }
    final = _GRAPH.invoke(init, config={"recursion_limit": 25})
    return final["answer"]
