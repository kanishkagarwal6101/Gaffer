"""Analysis tools exposed to the LLM via structured args (plan section 5).

M3 ships the two tools that prove the data->reasoning->viz path end to end:

- ``query_events(filters)`` — constrained, parameterized read over the DuckDB
  store (fixed filter interface, never free-form SQL; v2 hardening per the plan).
- ``shot_map(player)`` — pull a player's shots + xG, render an ``mplsoccer`` PNG,
  and return the interactive markers, the aggregate stats, and the image URL.

Each tool returns a plain JSON-serialisable ``dict`` (the agent feeds it back to
the LLM and threads the structured pieces into the final answer). ``TOOL_SPECS``
advertises the tools to the model; ``dispatch`` runs one by name.

``pass_network``, ``compare_players`` and ``tactics_lookup`` arrive in M4.
"""

from __future__ import annotations

import logging
import unicodedata
from pathlib import Path
from typing import Any

from ..data import store
from ..viz import pitch
from .schemas import QueryEventsArgs, ShotMapArgs

logger = logging.getLogger(__name__)

_SHOOTOUT_PERIOD = 5

# Columns surfaced from raw event rows so tool output stays compact and readable.
_EVENT_PREVIEW_COLS = [
    "player", "team", "type", "minute", "shot_outcome", "shot_statsbomb_xg",
]


def _fold(text: str) -> str:
    """Lower-case and strip accents so 'Julian Alvarez' matches 'Julián Álvarez'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower().strip()


def _resolve_player(name: str, con) -> str | None:
    """Map a possibly-short, possibly-unaccented name to the full StatsBomb name.

    Matching is accent- and case-insensitive: exact match wins, then a unique
    substring match, then a token-subset match (every query word appears in the
    candidate). Returns ``None`` if nothing matches.
    """
    players = store.list_players(con)
    folded = {_fold(p): p for p in players}
    key = _fold(name)
    if key in folded:
        return folded[key]

    hits = [p for p in players if key in _fold(p)]
    if not hits:
        query_tokens = set(key.split())
        hits = [p for p in players if query_tokens <= set(_fold(p).split())]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        logger.info("Ambiguous player '%s' -> %s; picking shortest", name, hits[:5])
        return min(hits, key=len)
    return None


def query_events(
    player: str | None = None,
    team: str | None = None,
    event_type: str | None = None,
    match_id: int | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Constrained query over the events view. Returns a compact row preview + count."""
    args = QueryEventsArgs(
        player=player, team=team, event_type=event_type, match_id=match_id, limit=limit
    )
    con = store.get_con()
    try:
        resolved = player
        if args.player:
            resolved = _resolve_player(args.player, con) or args.player
        df = store.query_events(
            con,
            player=resolved,
            team=args.team,
            event_type=args.event_type,
            match_id=args.match_id,
            limit=args.limit,
        )
        total = store.count_events(
            con,
            player=resolved,
            team=args.team,
            event_type=args.event_type,
            match_id=args.match_id,
        )
    finally:
        con.close()

    cols = [c for c in _EVENT_PREVIEW_COLS if c in df.columns]
    preview = df[cols].head(args.limit)
    # Round xG for readability.
    if "shot_statsbomb_xg" in preview.columns:
        preview = preview.assign(
            shot_statsbomb_xg=preview["shot_statsbomb_xg"].astype(float).round(3)
        )
    return {
        "tool": "query_events",
        "filters": args.model_dump(exclude_none=True),
        "resolved_player": resolved,
        "count": total,
        "rows_shown": int(len(preview)),
        "rows": preview.where(preview.notna(), None).to_dict(orient="records"),
    }


def shot_map(player: str) -> dict[str, Any]:
    """Pull a player's shots, render the pitch PNG, return markers + stats + image URL."""
    args = ShotMapArgs(player=player)
    con = store.get_con()
    try:
        resolved = _resolve_player(args.player, con)
        if resolved is None:
            return {
                "tool": "shot_map",
                "error": f"No player matching '{args.player}' in the loaded competition.",
                "shots": [],
            }
        df = store.query_events(con, player=resolved, event_type="Shot", limit=500)
    finally:
        con.close()

    if "period" in df.columns:
        df = df[df["period"] != _SHOOTOUT_PERIOD]

    markers: list[dict[str, Any]] = []
    for _, r in df.iterrows():
        loc = r.get("location")
        if loc is None or len(loc) < 2:
            continue
        xg = float(r.get("shot_statsbomb_xg") or 0.0)
        outcome = r.get("shot_outcome")
        markers.append(
            {
                "player": resolved,
                "team": r.get("team"),
                "minute": int(r["minute"]) if r.get("minute") is not None else None,
                "x": round(float(loc[0]), 2),
                "y": round(float(loc[1]), 2),
                "xg": round(xg, 4),
                "is_goal": outcome == "Goal",
                "outcome": str(outcome) if outcome is not None else None,
            }
        )

    goals = sum(1 for m in markers if m["is_goal"])
    total_xg = round(sum(m["xg"] for m in markers), 2)
    stats = {
        "shots": len(markers),
        "goals": goals,
        "xg": total_xg,
        "xg_diff": round(goals - total_xg, 2),
    }

    # Render the PNG via the M2 renderer (it wants x, y, shot_statsbomb_xg, is_goal).
    import pandas as pd

    shots_df = pd.DataFrame(
        {
            "x": [m["x"] for m in markers],
            "y": [m["y"] for m in markers],
            "shot_statsbomb_xg": [m["xg"] for m in markers],
            "is_goal": [m["is_goal"] for m in markers],
        }
    )
    image_url: str | None = None
    try:
        path = pitch.render_shot_map(shots_df, title=f"{resolved} — shot map")
        image_url = _static_url(path)
    except Exception as exc:  # rendering is best-effort; SVG markers are primary
        logger.warning("shot_map render failed for %s: %s", resolved, exc)

    return {
        "tool": "shot_map",
        "player": resolved,
        "stats": stats,
        "shots": markers,
        "image_url": image_url,
    }


def _static_url(fs_path: str) -> str:
    """Convert a rendered file path under app/static/ to its served URL."""
    p = Path(fs_path)
    try:
        rel = p.relative_to(pitch.STATIC_DIR.parents[0])  # .../static
        return f"/static/{rel.as_posix()}"
    except ValueError:
        return f"/static/shot_maps/{p.name}"


# --- LLM-facing tool specs + dispatch -------------------------------------

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_events",
            "description": (
                "Query the StatsBomb event store with structured filters and get a "
                "compact preview of matching rows plus the total count. Use this to "
                "look up facts (e.g. how many shots a player took, events in a match). "
                "All filters optional and combined with AND."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "player": {"type": "string", "description": "Player name (short ok, e.g. 'Messi')."},
                    "team": {"type": "string", "description": "Team name, e.g. 'Argentina'."},
                    "event_type": {"type": "string", "description": "Event type, e.g. 'Shot', 'Pass', 'Carry'."},
                    "match_id": {"type": "integer", "description": "StatsBomb match id."},
                    "limit": {"type": "integer", "description": "Max rows (1-500).", "default": 50},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "shot_map",
            "description": (
                "Produce a player's shot map: every shot with its location and xG, the "
                "aggregate totals (shots, goals, total xG, goals vs xG), and a rendered "
                "pitch image. Use this whenever the user asks about a player's shooting, "
                "chances, xG, or finishing."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "player": {"type": "string", "description": "Player name (short ok, e.g. 'Messi')."}
                },
                "required": ["player"],
            },
        },
    },
]

_REGISTRY = {
    "query_events": query_events,
    "shot_map": shot_map,
}


def dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run tool ``name`` with ``arguments``; return its dict (or an error dict)."""
    fn = _REGISTRY.get(name)
    if fn is None:
        return {"error": f"Unknown tool '{name}'."}
    try:
        return fn(**arguments)
    except Exception as exc:  # surface tool errors to the agent instead of crashing
        logger.exception("Tool %s failed", name)
        return {"tool": name, "error": f"{type(exc).__name__}: {exc}"}
