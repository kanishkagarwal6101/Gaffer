"""Generate the frontend shot-map data from the real StatsBomb cache.

Reads ``data_cache/events.parquet`` (WC 2022) for one match, transforms the
StatsBomb pitch coordinates into the design's SVG space, and writes
``frontend/src/shotmap.generated.json``. This keeps the frontend driven by real
ingested data instead of hand-authored numbers — run it after an ingest refresh.

Usage:  uv run python -m scripts.gen_shotmap
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

import pandas as pd

from app.data.ingest import EVENTS_PARQUET

# Argentina vs France — the WC 2022 final (StatsBomb match_id).
FINAL_MATCH_ID = 3869685
SUBJECT = "Argentina"
OPPONENT = "France"

# StatsBomb pitch is 120x80; the design canvas is 1050x680.
SB_LENGTH, SB_WIDTH = 120.0, 80.0
SVG_LENGTH, SVG_WIDTH = 1050.0, 680.0

# Penalty-shootout events live in period 5 — not part of the run-of-play map.
SHOOTOUT_PERIOD = 5

OUT_PATH = Path(__file__).resolve().parents[2] / "frontend" / "src" / "shotmap.generated.json"

# StatsBomb stores full legal names; map the few we surface to a short label.
SHORT_NAMES = {
    "Lionel Andrés Messi Cuccittini": "Messi",
    "Ángel Fabián Di María Hernández": "Di María",
    "Julián Álvarez": "Álvarez",
    "Lautaro Javier Martínez": "Martínez",
    "Kylian Mbappé Lottin": "Mbappé",
    "Randal Kolo Muani": "Kolo Muani",
}


def short_name(full: str) -> str:
    return SHORT_NAMES.get(full, full.split()[-1])


def to_svg(x: float, y: float, *, flip: bool) -> tuple[float, float]:
    """Map StatsBomb (x, y) to design SVG space.

    Every StatsBomb team attacks toward x=120 in its own frame; ``flip`` mirrors
    the opponent so the two sides attack opposite goals like the design shows.
    """
    if flip:
        x, y = SB_LENGTH - x, SB_WIDTH - y
    return round(x / SB_LENGTH * SVG_LENGTH, 1), round(y / SB_WIDTH * SVG_WIDTH, 1)


def raw_shots(df: pd.DataFrame, team: str, *, flip: bool) -> list[dict]:
    rows = df[df["team"] == team]
    shots = []
    for _, r in rows.iterrows():
        cx, cy = to_svg(r["location"][0], r["location"][1], flip=flip)
        shots.append(
            {
                "cx": cx,
                "cy": cy,
                "xg": round(float(r["shot_statsbomb_xg"]), 4),
                "goal": r["shot_outcome"] == "Goal",
                "player": short_name(r["player"]),
                "team": team,
                "minute": int(r["minute"]),
                "outcome": str(r["shot_outcome"]),
            }
        )
    return shots


def spread_coincident(shots: list[dict], *, gap: float = 11.0) -> list[dict]:
    """Fan out markers that share an identical spot so each stays visible.

    Some events legitimately occur at the exact same coordinate — e.g. France's
    two penalties from the spot — and would otherwise stack into a single dot,
    making a hat-trick read as fewer goals. We nudge each such group around its
    shared point by a few pixels. The shift is purely cosmetic (~1 yard) and
    leaves the underlying data untouched, so every real shot stays countable.
    """
    groups: dict[tuple[float, float], list[dict]] = defaultdict(list)
    for s in shots:
        groups[(s["cx"], s["cy"])].append(s)

    for (cx, cy), members in groups.items():
        if len(members) < 2:
            continue
        for i, s in enumerate(members):
            ang = 2 * math.pi * i / len(members)
            s["cx"] = round(cx + gap * math.cos(ang), 1)
            s["cy"] = round(cy + gap * math.sin(ang), 1)
    return shots


def team_stats(df: pd.DataFrame, team: str) -> dict:
    rows = df[df["team"] == team]
    xg = float(rows["shot_statsbomb_xg"].sum())
    goals = int((rows["shot_outcome"] == "Goal").sum())
    return {
        "xg": round(xg, 2),
        "shots": int(len(rows)),
        "goals": goals,
        "vsXg": round(goals - xg, 2),
    }


def main() -> None:
    df = pd.read_parquet(EVENTS_PARQUET)
    shots = df[(df["match_id"] == FINAL_MATCH_ID) & (df["type"] == "Shot")].copy()
    shots = shots[shots["period"] != SHOOTOUT_PERIOD]

    subject = spread_coincident(raw_shots(shots, SUBJECT, flip=False))
    opponent = spread_coincident(raw_shots(shots, OPPONENT, flip=True))
    stats = team_stats(shots, SUBJECT)

    top = max(subject, key=lambda s: s["xg"])
    top_chance = {
        "xg": top["xg"],
        "player": top["player"],
        "goal": top["goal"],
        "cx": top["cx"],
        "cy": top["cy"],
        "label": f"{top['xg']:.2f} xG · {top['player'].upper()}"
        + (" · GOAL" if top["goal"] else ""),
    }

    payload = {
        "_generated": "scripts/gen_shotmap.py — do not edit by hand",
        "matchId": FINAL_MATCH_ID,
        "competition": "FIFA WORLD CUP 2022 · FINAL",
        "home": {"team": SUBJECT, "goals": team_stats(shots, SUBJECT)["goals"]},
        "away": {"team": OPPONENT, "goals": team_stats(shots, OPPONENT)["goals"]},
        "subject": SUBJECT,
        "opponent": OPPONENT,
        "shots": {"subject": subject, "opponent": opponent},
        "stats": stats,
        "topChance": top_chance,
    }

    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"Wrote {OUT_PATH}")
    print(
        f"{SUBJECT}: {stats['shots']} shots, {stats['goals']} goals, xG {stats['xg']} "
        f"({stats['vsXg']:+} vs xG) · top chance {top_chance['label']}"
    )


if __name__ == "__main__":
    main()
