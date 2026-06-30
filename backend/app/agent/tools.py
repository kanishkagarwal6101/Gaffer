"""Analysis tools exposed to the LLM via structured args (plan section 5).

M3 ships the two tools that prove the data->reasoning->viz path end to end:

- ``query_events(filters)`` — constrained, parameterized read over the DuckDB
  store (fixed filter interface, never free-form SQL; v2 hardening per the plan).
- ``shot_map(player)`` — pull a player's shots + xG, render an ``mplsoccer`` PNG,
  and return the interactive markers, the aggregate stats, and the image URL.

Each tool returns a plain JSON-serialisable ``dict`` (the agent feeds it back to
the LLM and threads the structured pieces into the final answer). ``TOOL_SPECS``
advertises the tools to the model; ``dispatch`` runs one by name.

All five M3/M4 tools (``query_events``, ``shot_map``, ``pass_network``,
``compare_players``, ``tactics_lookup``) are wired through ``TOOL_SPECS``
and ``dispatch`` below.
"""

from __future__ import annotations

import logging
import unicodedata
from pathlib import Path
from typing import Any

from ..data import store
from ..viz import pitch
from .schemas import (
    ComparePlayersArgs,
    PassNetworkArgs,
    QueryEventsArgs,
    ShotMapArgs,
    TacticsLookupArgs,
)
from . import rag

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



# --- M4 tools ---------------------------------------------------------------


# Metric keys exposed to ``compare_players`` (everything ``store.player_metrics``
# returns). The default set excludes ``passes_completed`` so the radar stays
# focused on attacking output; the agent can override via ``metrics=``.
_AVAILABLE_METRICS = [
    "shots", "goals", "xg", "key_passes", "assists",
    "progressive_passes", "passes_completed",
]
_DEFAULT_METRICS = [
    "shots", "goals", "xg", "key_passes", "assists", "progressive_passes",
]


def _resolve_team(name: str, con) -> str | None:
    """Map a possibly-shortened team name to a real team in the data (accent/case-insensitive)."""
    teams = store.list_teams(con)
    folded = {_fold(t): t for t in teams}
    key = _fold(name)
    if key in folded:
        return folded[key]
    hits = [t for t in teams if key in _fold(t)]
    return hits[0] if len(hits) == 1 else None


def pass_network(
    team: str,
    opponent: str | None = None,
    match_id: int | None = None,
    until_minute: int | None = 60,
) -> dict[str, Any]:
    """Render a team's completed-pass network for one match.

    Resolves ``team`` (and the optional ``opponent``) to a concrete match in the
    loaded competition, fetches the completed passes from the store, renders the
    network PNG, and returns the resolved match metadata plus a top-edges
    summary the agent can cite.
    """
    args = PassNetworkArgs(
        team=team, opponent=opponent, match_id=match_id, until_minute=until_minute
    )
    con = store.get_con()
    try:
        resolved_team = _resolve_team(args.team, con) or args.team
        resolved_opp = _resolve_team(args.opponent, con) if args.opponent else None

        if args.match_id is not None:
            # Verify the team played in that match; pull the other side as opponent.
            matches = store.list_matches(con)
            row = matches[matches["match_id"] == args.match_id]
            if row.empty:
                return {"tool": "pass_network",
                        "error": f"No match with match_id={args.match_id}."}
            a, b = row.iloc[0]["team_a"], row.iloc[0]["team_b"]
            if resolved_team not in (a, b):
                return {"tool": "pass_network",
                        "error": f"{resolved_team} did not play in match {args.match_id} ({a} vs {b})."}
            opp = b if resolved_team == a else a
            match = {"match_id": int(args.match_id), "team": resolved_team, "opponent": opp}
        else:
            match = store.find_match(con, resolved_team, resolved_opp)
            if match is None:
                hint = f"{resolved_team} vs {resolved_opp}" if resolved_opp else resolved_team
                return {"tool": "pass_network",
                        "error": f"No match found for {hint} in the loaded competition."}

        passes = store.team_match_passes(con, match["team"], match["match_id"])
    finally:
        con.close()

    total_passes = int(len(passes))
    title = f"{match['team']} vs {match['opponent']} — pass network"
    image_url: str | None = None
    nodes: list[dict[str, Any]] = []
    top_edges: list[dict[str, Any]] = []
    try:
        result = pitch.render_pass_network(passes, title=title, until_minute=args.until_minute)
        image_url = _static_url(result["path"])
        nodes = result["nodes"]
        top_edges = result["edges"]
    except Exception as exc:  # rendering is best-effort
        logger.warning("pass_network render failed for %s: %s", title, exc)

    return {
        "tool": "pass_network",
        "team": match["team"],
        "opponent": match["opponent"],
        "match_id": match["match_id"],
        "until_minute": args.until_minute,
        "passes_completed": total_passes,
        "nodes": nodes,
        "top_edges": top_edges,
        "image_url": image_url,
    }


def compare_players(
    player_a: str,
    player_b: str,
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    """Compare two players' tournament metrics and render a radar.

    Returns both the raw per-player numbers and a PNG URL of the radar chart.
    """
    args = ComparePlayersArgs(player_a=player_a, player_b=player_b, metrics=metrics)
    con = store.get_con()
    try:
        a = _resolve_player(args.player_a, con)
        b = _resolve_player(args.player_b, con)
        if a is None or b is None:
            missing = []
            if a is None: missing.append(args.player_a)
            if b is None: missing.append(args.player_b)
            return {"tool": "compare_players",
                    "error": f"No player matching: {', '.join(missing)}."}
        m_a = store.player_metrics(con, a)
        m_b = store.player_metrics(con, b)
    finally:
        con.close()

    requested = args.metrics or _DEFAULT_METRICS
    keys = [k for k in requested if k in _AVAILABLE_METRICS]
    if not keys:
        return {"tool": "compare_players",
                "error": f"No valid metrics in {requested}; available: {_AVAILABLE_METRICS}."}

    metrics_a = {k: round(float(m_a[k]), 2) for k in keys}
    metrics_b = {k: round(float(m_b[k]), 2) for k in keys}

    image_url: str | None = None
    try:
        title = f"{pitch.short_name(a)} vs {pitch.short_name(b)} — WC22"
        path = pitch.render_player_radar(a, metrics_a, b, metrics_b, title=title)
        image_url = _static_url(path)
    except Exception as exc:
        logger.warning("compare_players radar failed for %s vs %s: %s", a, b, exc)

    return {
        "tool": "compare_players",
        "player_a": a,
        "player_b": b,
        "metrics": keys,
        "metrics_a": metrics_a,
        "metrics_b": metrics_b,
        "image_url": image_url,
    }


def tactics_lookup(query: str, top_k: int = 3) -> dict[str, Any]:
    """Semantic RAG over ``tactics_kb/`` — returns the top-k matching chunks."""
    args = TacticsLookupArgs(query=query, top_k=top_k)
    hits = rag.retrieve(args.query, top_k=args.top_k)
    return {
        "tool": "tactics_lookup",
        "query": args.query,
        "hits": [
            {"source": h["source"], "score": h["score"], "text": h["text"]}
            for h in hits
        ],
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
    {
        "type": "function",
        "function": {
            "name": "pass_network",
            "description": (
                "Render a team's completed-pass network for one match — nodes are "
                "players placed at their average pass location, edges weighted by "
                "the number of completed passes between them. Use this when the user "
                "asks about a team's build-up, structure, or how they connected in a "
                "specific match. Provide either ``opponent`` (e.g. 'Argentina') or "
                "``match_id``; ``team`` is always required."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "team": {"type": "string", "description": "Team whose network to render, e.g. 'France'."},
                    "opponent": {"type": "string", "description": "Opponent team in that match, e.g. 'Argentina'."},
                    "match_id": {"type": "integer", "description": "StatsBomb match id (alternative to opponent)."},
                    "until_minute": {"type": "integer", "description": "Cap the window at this minute (default 60).", "default": 60},
                },
                "required": ["team"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_players",
            "description": (
                "Compare two players over the loaded tournament: aggregates shots, "
                "goals, xG, key passes, assists, progressive passes and returns a "
                "radar chart PNG plus the raw per-player numbers. Use this when the "
                "user asks 'compare X and Y' or 'who was better at ...'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "player_a": {"type": "string", "description": "First player name (short ok, e.g. 'Mbappé')."},
                    "player_b": {"type": "string", "description": "Second player name (short ok, e.g. 'Messi')."},
                    "metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional subset of: shots, goals, xg, key_passes, assists, progressive_passes, passes_completed.",
                    },
                },
                "required": ["player_a", "player_b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "tactics_lookup",
            "description": (
                "Look up a tactical concept (low block, high press, overload, xG, "
                "pass network) from the local tactics knowledge base. Use this when "
                "the user asks 'what is X?' or wants to ground reasoning in a "
                "tactical definition. Returns short text chunks; cite them by source."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The question or concept to look up."},
                    "top_k": {"type": "integer", "description": "Max chunks (1-8, default 3).", "default": 3},
                },
                "required": ["query"],
            },
        },
    },
]

_REGISTRY = {
    "query_events": query_events,
    "shot_map": shot_map,
    "pass_network": pass_network,
    "compare_players": compare_players,
    "tactics_lookup": tactics_lookup,
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
