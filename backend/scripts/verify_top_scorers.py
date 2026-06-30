"""Sanity gate (plan section 4): ingest the cache, print the tournament top scorers.

Eyeball-verify the output against reality. For FIFA World Cup 2022
(competition_id=43, season_id=106) the Golden Boot race was:
Mbappe 8, Messi 7, then a cluster on 4 (Giroud, Alvarez, ...).

Run::

    uv run python -m scripts.verify_top_scorers
    uv run python -m scripts.verify_top_scorers --refresh
"""

from __future__ import annotations

import argparse
import logging

from app.data.ingest import ingest
from app.data.store import get_con, top_scorers


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Ingest and print tournament top scorers")
    parser.add_argument("--refresh", action="store_true", help="Force re-pull of the events cache")
    parser.add_argument("--limit", type=int, default=10, help="How many scorers to show")
    args = parser.parse_args(argv)

    ingest(refresh=args.refresh)

    con = get_con()
    try:
        df = top_scorers(con, limit=args.limit)
    finally:
        con.close()

    print("\nTop scorers (excluding penalty shootouts):\n")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
