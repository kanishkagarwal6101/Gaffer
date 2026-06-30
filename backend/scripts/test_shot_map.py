"""Render a player's shot map and print summary stats (plan sections 4, 5).

Proves the data -> viz path end to end: pull a player's shots from the DuckDB
store, render an mplsoccer PNG, and report totals (shots, xG, goals, and
over/under-performance vs xG).

Usage:
    uv run python -m scripts.test_shot_map "Lionel Andrés Messi Cuccittini"
    uv run python -m scripts.test_shot_map messi      # fuzzy match also works
"""

from __future__ import annotations

import argparse

from app.data.store import get_con, get_player_shots, list_players
from app.viz.pitch import STATIC_DIR, render_shot_map

DEFAULT_PLAYER = "Lionel Andrés Messi Cuccittini"


def resolve_player(name: str) -> str | None:
    """Map a possibly-partial name to a full StatsBomb player name.

    Exact (case-insensitive) match wins; otherwise fall back to a unique-ish
    substring match. Returns ``None`` if nothing matches.
    """
    con = get_con()
    try:
        players = list_players(con)
    finally:
        con.close()

    lowered = name.strip().lower()
    for p in players:
        if p.lower() == lowered:
            return p
    matches = [p for p in players if lowered in p.lower()]
    if matches:
        return min(matches, key=len)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a player's shot map + stats")
    parser.add_argument("player", nargs="?", default=DEFAULT_PLAYER, help="player name (full or partial)")
    args = parser.parse_args()

    full_name = resolve_player(args.player)
    if full_name is None:
        print(f'No player matching "{args.player}" in the loaded competition.')
        return
    if full_name != args.player:
        print(f'Resolved "{args.player}" -> "{full_name}"')

    shots = get_player_shots(full_name)

    total_shots = int(len(shots))
    total_xg = float(shots["shot_statsbomb_xg"].sum()) if total_shots else 0.0
    goals = int(shots["is_goal"].sum()) if total_shots else 0
    vs_xg = goals - total_xg

    title = f"{full_name} \u2014 shot map"
    png_path = render_shot_map(shots, title, out_dir=STATIC_DIR)

    print(f"\nPlayer:          {full_name}")
    if total_shots == 0:
        print("No shots on record \u2014 rendered an empty pitch.")
    else:
        print(f"Total shots:     {total_shots}")
        print(f"Total xG:        {total_xg:.2f}")
        print(f"Goals:           {goals}")
        print(f"Goals - xG:      {vs_xg:+.2f}  ({'over' if vs_xg >= 0 else 'under'}-performance)")
    print(f"Saved PNG:       {png_path}")


if __name__ == "__main__":
    main()
