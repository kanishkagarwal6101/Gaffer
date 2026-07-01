"""Three-case verification for the M5 grounding gate.

1. **Normal question** — full agent on a real question; assert grounded=True and
   the answer contains at least one canonical fact value.
2. **Forced hallucination** — rigged draft with wrong numbers; assert the check
   catches and corrects all three fabricated values.
3. **Right number, wrong metric** — draft says "5 key passes" when the fact is
   shots=5 / key_passes=0; the programmatic check PASSES (5 exists in facts) but
   the LLM verify pass must catch the metric-binding error and the rewrite must
   fix it.

Run:
    uv run python -m scripts.test_grounding
"""

from __future__ import annotations

import logging
import re
import sys

from app.agent import grounding
from app.agent.graph import run

# --- case 2 fixtures (outright hallucination) --------------------------------

_HALLUCINATED_DRAFT = (
    "Messi was ruthless in front of goal — he took 13 shots, scored 9 goals, "
    "and produced 4.72 expected goals over the tournament."
)
_TRUTH_TOOL_RESULTS = [
    {
        "tool": "shot_map",
        "player": "Lionel Andrés Messi Cuccittini",
        "stats": {"shots": 5, "goals": 2, "xg": 1.35, "xg_diff": 0.65},
        "shots": [
            {"minute": 21, "xg": 0.08, "is_goal": False, "outcome": "Off T"},
            {"minute": 34, "xg": 0.42, "is_goal": True,  "outcome": "Goal"},
            {"minute": 56, "xg": 0.11, "is_goal": False, "outcome": "Saved"},
            {"minute": 63, "xg": 0.19, "is_goal": True,  "outcome": "Goal"},
            {"minute": 88, "xg": 0.55, "is_goal": False, "outcome": "Blocked"},
        ],
        "image_url": None,
    }
]

# --- case 3 fixtures (right number, wrong metric) -------------------------
# The programmatic check will PASS — the number 5 exists in the facts as
# "Messi shots=5" and the number 2 exists as "Messi goals=2".
# The LLM verify pass must catch that "5 key passes" misuses the shots count
# and "2 shots" misuses the goals count.

_WRONG_METRIC_DRAFT = (
    "Messi was a creative force in the tournament — he registered 5 key passes "
    "and managed just 2 shots on the way to his side's victory."
)
_WRONG_METRIC_TOOL_RESULTS = [
    {
        "tool": "compare_players",
        "player_a": "Lionel Andrés Messi Cuccittini",
        "player_b": "Kylian Mbappé",
        "metrics": ["shots", "goals", "xg", "key_passes"],
        "metrics_a": {"shots": 5, "goals": 2, "xg": 1.35, "key_passes": 0},
        "metrics_b": {"shots": 12, "goals": 8, "xg": 3.42, "key_passes": 4},
        "image_url": None,
    }
]


# --- helpers -----------------------------------------------------------------


def _fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def _pass(msg: str) -> None:
    print(f"PASS: {msg}")


def _numbers(text: str) -> list[str]:
    return grounding._NUMBER_RE.findall(text)


# --- test cases --------------------------------------------------------------


def case_normal() -> None:
    print("\n=== case 1: normal question (real agent, real tools) ===")
    question = "How many shots did Messi take in this tournament, and what was his xG?"
    print(f"Q: {question}")
    answer = run(question)
    print(f"A: {answer.answer_text}")
    print(f"grounded: {answer.grounded}")
    for note in answer.verification_notes:
        print(f"  * {note}")

    if not answer.answer_text.strip():
        _fail("agent returned an empty answer")
    if not answer.grounded:
        _fail(f"expected grounded=True, got False; notes={answer.verification_notes}")
    if not _numbers(answer.answer_text):
        _fail("answer_text contains no numeric claim — grounding is vacuous")
    _pass("normal question is grounded and numeric")


def case_hallucination() -> None:
    print("\n=== case 2: forced hallucination (fabricated numbers, real tool output) ===")
    print(f"draft: {_HALLUCINATED_DRAFT}")

    facts = grounding.collect_facts(_TRUTH_TOOL_RESULTS)
    print(f"facts: {[(f.label, f.value) for f in facts]}")

    candidates = grounding.programmatic_check(_HALLUCINATED_DRAFT, facts)
    print(f"programmatic unmatched tokens: {[c['token'] for c in candidates]}")
    for bogus in ("13", "9", "4.72"):
        if not any(c["token"] == bogus for c in candidates):
            _fail(f"programmatic check missed hallucinated token {bogus!r}")
    _pass("programmatic check flags all three hallucinated numbers")

    result = grounding.verify(_HALLUCINATED_DRAFT, _TRUTH_TOOL_RESULTS)
    print(f"rewritten draft: {result.draft}")
    print(f"grounded: {result.grounded}")
    for note in result.notes:
        print(f"  * {note}")

    if result.draft == _HALLUCINATED_DRAFT:
        _fail("verify() left the hallucinated draft unchanged")
    for bogus in ("13", "9", "4.72"):
        if re.search(rf"(?<![\w\.]){bogus}(?![\w\.])", result.draft):
            _fail(f"hallucinated token {bogus!r} survived the rewrite: {result.draft!r}")
    _pass("hallucinated numbers were removed / replaced by the rewrite")

    if result.grounded:
        _pass("rewrite produced a grounded draft")
    else:
        if not result.notes:
            _fail("draft was not grounded but produced no audit trail")
        print("note: rewrite produced an ungrounded result but the hallucination was caught")


def case_wrong_metric() -> None:
    print("\n=== case 3: right number, wrong metric (LLM-only catch) ===")
    print(f"draft: {_WRONG_METRIC_DRAFT}")

    facts = grounding.collect_facts(_WRONG_METRIC_TOOL_RESULTS)
    print(f"facts: {[(f.label, f.value) for f in facts]}")

    # Step 1: programmatic check must PASS — 5 and 2 both exist in facts.
    candidates = grounding.programmatic_check(_WRONG_METRIC_DRAFT, facts)
    print(f"programmatic unmatched tokens: {[c['token'] for c in candidates]}")
    if candidates:
        _fail(
            f"programmatic check should NOT flag tokens when numbers appear in facts; "
            f"got {candidates}"
        )
    _pass("programmatic check correctly passes (numbers 5 and 2 exist in facts)")

    # Step 2: full verify — the LLM must catch the metric mismatch and rewrite.
    result = grounding.verify(_WRONG_METRIC_DRAFT, _WRONG_METRIC_TOOL_RESULTS)
    print(f"rewritten draft: {result.draft}")
    print(f"grounded: {result.grounded}")
    for note in result.notes:
        print(f"  * {note}")

    # The metric-binding error should be caught: the rewritten draft must not
    # claim "5 key passes" (Messi key_passes=0) or "2 shots" (actual shots=5).
    if re.search(r"5 key pass", result.draft, flags=re.IGNORECASE):
        _fail(f"metric-binding error '5 key passes' survived verify: {result.draft!r}")
    if re.search(r"2 shot", result.draft, flags=re.IGNORECASE):
        _fail(f"metric-binding error '2 shots' survived verify: {result.draft!r}")

    if result.draft == _WRONG_METRIC_DRAFT:
        _fail("verify() left the metric-binding draft unchanged — LLM did not catch the error")

    _pass("LLM verify caught the metric-binding error and the rewrite fixed it")


# --- entry point -------------------------------------------------------------


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    case_normal()
    case_hallucination()
    case_wrong_metric()
    print("\nALL PASS")


if __name__ == "__main__":
    main()
