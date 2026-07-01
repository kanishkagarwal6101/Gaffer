"""Grounding / verification for the agent's drafted answer (plan section 5, M5).

After the planner writes a draft, this module:

1. Extracts every canonical number the tools produced into a flat ``Fact`` set
   (the source-of-truth for the turn).
2. Runs a **programmatic check**: every numeric token in the draft must appear
   in the fact set within a small rounding tolerance. Unmatched tokens become
   candidate unsupported claims. NOTE: this confirms a number EXISTS in the
   canonical facts but not that it's bound to the RIGHT metric — the LLM
   verify pass (step 3) is required to catch metric-binding errors.
3. Runs a **cheap-LLM verify pass** (Groq primary, Gemini Flash-Lite fallback)
   as backstop. It sees the full fact set and draft and flags:
   (a) numbers not present in any fact within tolerance,
   (b) numbers attributed to the wrong subject (right number, wrong player/team),
   (c) numbers attributed to the wrong metric for that subject — e.g. the draft
       says "5 key passes" but the fact shows key_passes=0 and shots=5; the 5
       exists in the facts but is bound to the wrong stat.
4. If the draft is not grounded, one **rewrite pass** replaces the offending
   figures with verified values (or removes them). The rewritten draft is
   re-checked before returning.

The output (``VerificationResult``) carries ``grounded``, ``draft`` (possibly
rewritten), and ``notes`` — the audit trail that lands in
``AgentAnswer.grounded`` / ``AgentAnswer.verification_notes``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from .. import llm

logger = logging.getLogger(__name__)

# Absolute rounding tolerance for the programmatic check. Matches the level of
# precision the tools emit (2dp for xG, integers for counts) plus a hair of
# slack so "0.72" matches a fact stored as 0.72 or 0.718.
_TOLERANCE = 0.05
# Cap on the number of rewrite hops so a stubborn draft can't burn free-tier quota.
_MAX_REWRITES = 1
# Standalone numeric tokens: integer or decimal, not glued to a word/digit/dot.
_NUMBER_RE = re.compile(r"(?<![\w\.])\d+(?:\.\d+)?(?![\w\.])")


@dataclass(frozen=True)
class Fact:
    """A single canonical number the tools produced for this turn."""

    label: str
    value: float
    source: str


@dataclass
class VerificationResult:
    """Outcome of the grounding pass — what the answer node writes into the answer."""

    grounded: bool
    draft: str
    notes: list[str] = field(default_factory=list)
    unsupported: list[dict[str, str]] = field(default_factory=list)


# --- 1) fact collection ---------------------------------------------------


def collect_facts(tool_results: list[dict[str, Any]]) -> list[Fact]:
    """Turn every successful tool result into a flat list of canonical numeric facts."""
    facts: list[Fact] = []
    for r in tool_results:
        if r.get("error"):
            continue
        collector = _COLLECTORS.get(r.get("tool"))
        if collector is None:
            continue
        facts += collector(r)
    return facts


def _c_shot_map(r: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []
    player = r.get("player", "player")
    stats = r.get("stats") or {}
    for k in ("shots", "goals"):
        if k in stats:
            facts.append(Fact(f"{player} {k}", float(stats[k]), "shot_map"))
    if "xg" in stats:
        facts.append(Fact(f"{player} xG", float(stats["xg"]), "shot_map"))
    if "xg_diff" in stats:
        facts.append(Fact(f"{player} xG diff", float(stats["xg_diff"]), "shot_map"))
    for i, m in enumerate(r.get("shots", []) or []):
        if "xg" in m:
            facts.append(Fact(f"{player} shot #{i + 1} xG", float(m["xg"]), "shot_map"))
        if m.get("minute") is not None:
            facts.append(Fact(f"{player} shot #{i + 1} minute", float(m["minute"]), "shot_map"))
    return facts


def _c_query_events(r: dict[str, Any]) -> list[Fact]:
    if "count" not in r:
        return []
    bits: list[str] = []
    if r.get("resolved_player"):
        bits.append(str(r["resolved_player"]))
    f = r.get("filters") or {}
    if f.get("team"):
        bits.append(str(f["team"]))
    if f.get("event_type"):
        bits.append(str(f["event_type"]))
    label = (" ".join(bits) + " events") if bits else "matching events"
    return [Fact(label, float(r["count"]), "query_events")]


def _c_pass_network(r: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []
    team, opp = r.get("team"), r.get("opponent")
    match = f"{team} vs {opp}" if team and opp else "match"
    if "passes_completed" in r:
        facts.append(Fact(
            f"{match} completed passes", float(r["passes_completed"]), "pass_network"
        ))
    if r.get("until_minute") is not None:
        facts.append(Fact(
            f"{match} until minute", float(r["until_minute"]), "pass_network"
        ))
    for e in (r.get("top_edges") or [])[:8]:
        if "passes" in e:
            facts.append(Fact(
                f"{e.get('a')} <-> {e.get('b')} passes",
                float(e["passes"]),
                "pass_network",
            ))
    for n in (r.get("nodes") or []):
        if isinstance(n, dict) and "passes" in n:
            facts.append(Fact(
                f"{n.get('player')} passes", float(n["passes"]), "pass_network"
            ))
    return facts


def _c_compare_players(r: dict[str, Any]) -> list[Fact]:
    facts: list[Fact] = []
    a, b = r.get("player_a"), r.get("player_b")
    for label, metrics in ((a, r.get("metrics_a") or {}), (b, r.get("metrics_b") or {})):
        if not label:
            continue
        for k, v in metrics.items():
            facts.append(Fact(f"{label} {k}", float(v), "compare_players"))
    return facts


_COLLECTORS = {
    "shot_map": _c_shot_map,
    "query_events": _c_query_events,
    "pass_network": _c_pass_network,
    "compare_players": _c_compare_players,
    # tactics_lookup returns RAG scores, not stat claims -> no facts.
}


# --- 2) programmatic check -------------------------------------------------


def _extract_number_tokens(text: str) -> list[tuple[str, float, int]]:
    """Every standalone numeric token as ``(token, value, position)``."""
    return [
        (m.group(0), float(m.group(0)), m.start())
        for m in _NUMBER_RE.finditer(text)
    ]


def _fact_supports(value: float, facts: list[Fact]) -> Fact | None:
    """Closest fact within ``_TOLERANCE`` of ``value``, or ``None``."""
    best: tuple[float, Fact] | None = None
    for f in facts:
        d = abs(value - f.value)
        if d <= _TOLERANCE + 1e-9 and (best is None or d < best[0]):
            best = (d, f)
    return best[1] if best else None


def _context_around(text: str, pos: int, span: int = 40) -> str:
    lo = max(0, pos - span)
    hi = min(len(text), pos + span)
    return text[lo:hi].replace("\n", " ").strip()


def programmatic_check(draft: str, facts: list[Fact]) -> list[dict[str, str]]:
    """Return numeric tokens in ``draft`` that no fact supports within tolerance.

    NOTE: passing here only means the value EXISTS in the fact set, NOT that
    it is attributed to the correct metric. The LLM verify pass is responsible
    for catching metric-binding errors (right number, wrong stat).
    """
    unmatched: list[dict[str, str]] = []
    for token, value, pos in _extract_number_tokens(draft):
        if _fact_supports(value, facts) is None:
            unmatched.append({"token": token, "context": _context_around(draft, pos)})
    return unmatched


# --- 3) LLM verify pass ----------------------------------------------------

_VERIFY_SYSTEM = (
    "You are a strict football stat auditor. Given a set of verified facts and "
    "a draft answer, decide whether every numeric CLAIM in the draft is supported.\n\n"
    "Ignore innocuous numbers: minute stamps, years, jersey numbers, ordinals, "
    "and counts of general concepts ('three key ideas').\n\n"
    "A numeric claim is UNSUPPORTED when it falls into any of these three cases:\n"
    "(a) The number does not match any fact value within 0.05 tolerance.\n"
    "(b) The number matches a fact value for a DIFFERENT subject — e.g. the draft "
    "says 'Mbappé scored 5 goals' when shots=5 belongs to Messi, not Mbappé.\n"
    "(c) The number matches a fact value for the correct subject but describes the "
    "WRONG METRIC — e.g. the draft says 'Messi had 5 key passes' when the facts "
    "show Messi key_passes=0 and Messi shots=5; the 5 exists but is bound to the "
    "wrong stat.\n\n"
    "For each unsupported claim you find, include the token, the surrounding "
    "context, and the reason referencing the actual fact values.\n\n"
    "Return ONLY a JSON object of the form:\n"
    "  {\"grounded\": true|false, \"unsupported\": [{\"token\": \"12\", "
    "\"context\": \"took 12 shots\", \"reason\": \"actual shots = 5\"}]}\n"
    'If nothing is unsupported, "grounded" MUST be true and "unsupported" MUST be [].'
)


def _facts_json(facts: list[Fact]) -> str:
    return json.dumps(
        [{"label": f.label, "value": round(f.value, 4), "source": f.source} for f in facts],
        ensure_ascii=False,
    )


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort: pull the first ``{...}`` block from the LLM response."""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def llm_verify(
    draft: str, facts: list[Fact], candidates: list[dict[str, str]]
) -> dict[str, Any]:
    """LLM backstop: flag semantically unsupported numeric claims.

    Catches metric-binding errors that the programmatic check misses (a number
    that EXISTS in the fact set but describes the wrong stat for that subject).

    Returns ``{"grounded": bool, "unsupported": [...]}``. Falls back to the
    programmatic result if the verifier response can't be parsed or every model
    in the verify chain fails.
    """
    prompt = (
        "Facts (canonical numeric truth for this turn):\n"
        f"{_facts_json(facts)}\n\n"
        f"Draft answer:\n\"\"\"\n{draft}\n\"\"\"\n\n"
        "The programmatic check flagged these tokens as not matching any fact "
        "within tolerance 0.05 (some may be innocuous — decide):\n"
        f"{json.dumps(candidates, ensure_ascii=False)}\n\n"
        "Also check ALL numeric claims in the draft — including those NOT flagged "
        "above — for metric-binding errors (case c): a number that appears in the "
        "facts but is attributed to the wrong stat for that player or team."
    )
    try:
        msg = llm.verify_chat(
            [
                {"role": "system", "content": _VERIFY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:
        logger.warning("llm_verify failed (%s); falling back to programmatic result", exc)
        return {"grounded": not candidates, "unsupported": candidates}

    parsed = _parse_json_object(getattr(msg, "content", "") or "")
    if not isinstance(parsed, dict) or "grounded" not in parsed:
        logger.warning("llm_verify returned unparseable JSON; falling back")
        return {"grounded": not candidates, "unsupported": candidates}

    unsup = parsed.get("unsupported") or []
    if not isinstance(unsup, list):
        unsup = []
    return {"grounded": bool(parsed["grounded"]) and not unsup, "unsupported": unsup}


# --- 4) rewrite -----------------------------------------------------------

_REWRITE_SYSTEM = (
    "You correct a football analyst's draft. Preserve the analytical tone, "
    "structure, and length. Replace incorrect numeric claims with the verified "
    "values from the facts below, or remove/rephrase any numeric claim that has "
    "no matching verified value. Do not invent numbers. Keep every player, team, "
    "and tactical assertion that the facts do not contradict.\n\n"
    "Pay special attention to metric-binding errors: if the draft says '5 key "
    "passes' but the facts show key_passes=0 and shots=5, replace '5 key passes' "
    "with the correct stat — do NOT keep the number 5 and change the label.\n\n"
    "Return ONLY the corrected answer text — no preface, no JSON, no bullets."
)


def llm_rewrite(
    draft: str, facts: list[Fact], unsupported: list[dict[str, str]]
) -> str:
    """Rewrite the draft so it only cites facts; return the new draft (or old on failure)."""
    prompt = (
        "Verified facts:\n"
        f"{_facts_json(facts)}\n\n"
        f"Draft:\n\"\"\"\n{draft}\n\"\"\"\n\n"
        "Unsupported claims flagged in the draft:\n"
        f"{json.dumps(unsupported, ensure_ascii=False)}\n"
    )
    try:
        msg = llm.verify_chat(
            [
                {"role": "system", "content": _REWRITE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
        )
    except Exception as exc:
        logger.warning("llm_rewrite failed (%s); returning draft unchanged", exc)
        return draft
    return (getattr(msg, "content", "") or "").strip() or draft


# --- top-level ------------------------------------------------------------


def verify(draft: str, tool_results: list[dict[str, Any]]) -> VerificationResult:
    """Verify ``draft`` against ``tool_results``; rewrite once if the check fails."""
    notes: list[str] = []
    facts = collect_facts(tool_results)
    if not facts:
        # Tactics-only answers (RAG) or errors: nothing to verify numerically.
        notes.append("no numeric facts collected from tool outputs; skipping verification")
        return VerificationResult(grounded=True, draft=draft, notes=notes)

    notes.append(f"collected {len(facts)} facts from tools")

    current = draft
    unsupported: list[dict[str, str]] = []
    for attempt in range(_MAX_REWRITES + 1):
        candidates = programmatic_check(current, facts)
        notes.append(
            f"attempt {attempt}: programmatic check "
            + ("passed" if not candidates else f"flagged {len(candidates)} unmatched token(s)")
        )

        verdict = llm_verify(current, facts, candidates)
        unsupported = verdict.get("unsupported") or []
        grounded = bool(verdict.get("grounded")) and not unsupported
        summary = f"attempt {attempt}: LLM verify -> grounded={grounded}"
        if unsupported:
            summary += f", unsupported={[u.get('token') for u in unsupported]}"
        notes.append(summary)

        if grounded:
            return VerificationResult(grounded=True, draft=current, notes=notes)

        if attempt >= _MAX_REWRITES:
            notes.append("rewrite budget exhausted; returning draft as ungrounded")
            return VerificationResult(
                grounded=False, draft=current, notes=notes, unsupported=unsupported
            )

        notes.append(f"attempt {attempt}: rewriting draft to remove unsupported claims")
        current = llm_rewrite(current, facts, unsupported)

    # Unreachable — the loop always returns — but keeps type checkers happy.
    return VerificationResult(
        grounded=False, draft=current, notes=notes, unsupported=unsupported
    )
