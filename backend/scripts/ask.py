"""Ask the Gaffer agent one question from the command line (plan section 5).

Runs the M3 LangGraph loop (question -> plan -> tool(s) -> grounded answer) and
prints the answer text, the cited stats, and any rendered PNG path.

Requires GEMINI_API_KEY (and optionally GROQ_API_KEY) in the repo-root ``.env``.

Usage:
    uv run python -m scripts.ask "Show me Messi's shot map from this tournament"
    uv run python -m scripts.ask "How many shots did Mbappe take?"
"""

from __future__ import annotations

import argparse
import logging

from app.agent.graph import run
from app.viz import pitch

DEFAULT_QUESTION = "Show me Messi's shot map from this tournament"


def _local_path(visual_url: str) -> str:
    """Map a served ``/static/...`` URL back to its on-disk path, when it exists."""
    static_root = pitch.STATIC_DIR.parents[0]  # .../app/static
    rel = visual_url.removeprefix("/static/")
    candidate = static_root / rel
    return str(candidate) if candidate.exists() else visual_url


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Ask the Gaffer agent a question")
    parser.add_argument(
        "question",
        nargs="*",
        help="The question to ask (quote it, or pass as separate words).",
    )
    args = parser.parse_args(argv)
    question = " ".join(args.question).strip() or DEFAULT_QUESTION

    print(f"\nQ: {question}\n")
    answer = run(question)

    print(f"A: {answer.answer_text}\n")

    if answer.cited_stats:
        print("Cited stats:")
        for c in answer.cited_stats:
            print(f"  - {c.label}: {c.value}  ({c.source})")
    else:
        print("Cited stats: (none)")

    if answer.visuals:
        print("\nVisuals:")
        for url in answer.visuals:
            local = _local_path(url)
            line = f"  - {url}"
            if local != url:
                line += f"  ->  {local}"
            print(line)
    else:
        print("\nVisuals: (none)")


if __name__ == "__main__":
    main()
