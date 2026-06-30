"""DuckDB views + query helpers (plan section 4).

Builds a DuckDB view over ``data_cache/events.parquet`` — the queryable layer
the agent reads — and exposes *constrained* query helpers over key columns:
``player``, ``team``, ``type`` (Pass/Shot/Carry...), ``location`` ``[x, y]``,
shot xG (``shot_statsbomb_xg``), pass ``pass_end_location``, and the shot
freeze-frame (positions of all players at the shot).

Callers use the typed helpers below; free-form SQL from callers is deliberately
not exposed in v1 (see plan section 5 — that is a v2 hardening task).
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

from .ingest import EVENTS_PARQUET, ingest

# Name of the DuckDB view exposed over the parquet cache.
_VIEW = "events"

# Shootout penalties (period 5) are not tournament goals; exclude by default
# so counts line up with official tallies.
_SHOOTOUT_PERIOD = 5


def get_con(parquet_path: Path = EVENTS_PARQUET, auto_ingest: bool = True) -> duckdb.DuckDBPyConnection:
    """Return an in-memory DuckDB connection with an ``events`` view over the cache.

    If the parquet cache is missing and ``auto_ingest`` is set, the ingest is run
    first. The connection reads the parquet directly (we never mutate it).
    """
    if not parquet_path.exists():
        if not auto_ingest:
            raise FileNotFoundError(
                f"Events cache not found at {parquet_path}. Run `python -m app.data.ingest` first."
            )
        ingest(refresh=False)

    con = duckdb.connect(database=":memory:")
    # CREATE VIEW cannot take a bound parameter, so inline the path with
    # single-quotes escaped (the path is internal, never caller-supplied).
    safe_path = str(parquet_path).replace("'", "''")
    con.execute(f"CREATE OR REPLACE VIEW {_VIEW} AS SELECT * FROM read_parquet('{safe_path}')")
    return con


def _columns(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[1] for row in con.execute(f"PRAGMA table_info('{_VIEW}')").fetchall()}


def top_scorers(
    con: duckdb.DuckDBPyConnection | None = None,
    limit: int = 10,
    include_shootouts: bool = False,
) -> pd.DataFrame:
    """Return players ranked by goals scored.

    Goals = shots with ``shot_outcome = 'Goal'``. Penalty-shootout goals
    (period 5) are excluded unless ``include_shootouts`` is set.
    """
    owns = con is None
    con = con or get_con()
    try:
        where = ["type = 'Shot'", "shot_outcome = 'Goal'"]
        if not include_shootouts:
            where.append(f"period <> {_SHOOTOUT_PERIOD}")
        clause = " AND ".join(where)
        return con.execute(
            f"""
            SELECT player, team, COUNT(*) AS goals
            FROM {_VIEW}
            WHERE {clause}
            GROUP BY player, team
            ORDER BY goals DESC, player ASC
            LIMIT ?
            """,
            [limit],
        ).df()
    finally:
        if owns:
            con.close()


def query_events(
    con: duckdb.DuckDBPyConnection,
    player: str | None = None,
    team: str | None = None,
    event_type: str | None = None,
    match_id: int | None = None,
    limit: int = 100,
) -> pd.DataFrame:
    """Constrained, parameterized query over the events view.

    All filters are optional and combined with AND. This is the fixed-interface
    query layer the agent's ``query_events`` tool builds on (no free-form SQL).
    """
    where, params = _event_filters(player, team, event_type, match_id)
    params.append(limit)
    return con.execute(f"SELECT * FROM {_VIEW} {where} LIMIT ?", params).df()


def _event_filters(
    player: str | None,
    team: str | None,
    event_type: str | None,
    match_id: int | None,
) -> tuple[str, list[object]]:
    """Build a parameterized WHERE clause shared by query_events/count_events."""
    clauses: list[str] = []
    params: list[object] = []
    if player is not None:
        clauses.append("player = ?")
        params.append(player)
    if team is not None:
        clauses.append("team = ?")
        params.append(team)
    if event_type is not None:
        clauses.append("type = ?")
        params.append(event_type)
    if match_id is not None:
        clauses.append("match_id = ?")
        params.append(match_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def count_events(
    con: duckdb.DuckDBPyConnection,
    player: str | None = None,
    team: str | None = None,
    event_type: str | None = None,
    match_id: int | None = None,
) -> int:
    """True total of events matching the filters (independent of any row limit)."""
    where, params = _event_filters(player, team, event_type, match_id)
    return int(con.execute(f"SELECT COUNT(*) FROM {_VIEW} {where}", params).fetchone()[0])


def player_shots(con: duckdb.DuckDBPyConnection, player: str) -> pd.DataFrame:
    """Return all shot events for a player, with xG and outcome."""
    cols = _columns(con)
    select = [
        "player", "team", "type", "shot_outcome", "shot_statsbomb_xg",
        "location", "match_id", "period",
    ]
    select = [c for c in select if c in cols]
    return con.execute(
        f"SELECT {', '.join(select)} FROM {_VIEW} WHERE type = 'Shot' AND player = ?",
        [player],
    ).df()


def get_player_shots(player_name: str, include_shootouts: bool = False) -> pd.DataFrame:
    """Return one player's shots for the loaded competition, ready for plotting.

    Self-contained convenience wrapper around the structured ``player_shots``
    helper (no free-form SQL): opens its own connection, splits the StatsBomb
    ``location`` ``[x, y]`` into numeric ``x``/``y`` columns, and derives a
    boolean ``is_goal``. Penalty-shootout attempts (period 5) are excluded by
    default so totals match run-of-play tallies.

    Returns a DataFrame with columns ``x``, ``y``, ``shot_statsbomb_xg``,
    ``is_goal`` (empty with those columns if the player has no shots).
    """
    empty = pd.DataFrame(columns=["x", "y", "shot_statsbomb_xg", "is_goal"])
    con = get_con()
    try:
        df = player_shots(con, player_name)
    finally:
        con.close()

    if df.empty:
        return empty

    if not include_shootouts and "period" in df.columns:
        df = df[df["period"] != _SHOOTOUT_PERIOD]
    if df.empty:
        return empty

    locs = df["location"].apply(lambda loc: (None, None) if loc is None else (loc[0], loc[1]))
    out = pd.DataFrame(
        {
            "x": [pt[0] for pt in locs],
            "y": [pt[1] for pt in locs],
            "shot_statsbomb_xg": df["shot_statsbomb_xg"].astype(float).fillna(0.0).to_numpy(),
            "is_goal": (df["shot_outcome"] == "Goal").to_numpy(),
        }
    )
    return out.dropna(subset=["x", "y"]).reset_index(drop=True)


def list_teams(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Distinct team names present in the data."""
    return [r[0] for r in con.execute(f"SELECT DISTINCT team FROM {_VIEW} ORDER BY team").fetchall()]


def list_players(con: duckdb.DuckDBPyConnection, team: str | None = None) -> list[str]:
    """Distinct player names, optionally filtered to one team."""
    if team is not None:
        rows = con.execute(
            f"SELECT DISTINCT player FROM {_VIEW} WHERE team = ? AND player IS NOT NULL ORDER BY player",
            [team],
        ).fetchall()
    else:
        rows = con.execute(
            f"SELECT DISTINCT player FROM {_VIEW} WHERE player IS NOT NULL ORDER BY player"
        ).fetchall()
    return [r[0] for r in rows]


# --- M4 helpers: passes for pass_network, match resolution, player metrics ---


def list_matches(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """Return one row per match with ``match_id`` and the two teams sorted alphabetically.

    Used by the agent's pass_network tool to resolve a natural-language match
    ("France vs Argentina") to a real ``match_id``.
    """
    return con.execute(
        f"""
        SELECT match_id,
               MIN(team) AS team_a,
               MAX(team) AS team_b
        FROM {_VIEW}
        WHERE team IS NOT NULL
        GROUP BY match_id
        HAVING COUNT(DISTINCT team) = 2
        ORDER BY match_id
        """
    ).df()


def find_match(
    con: duckdb.DuckDBPyConnection,
    team: str,
    opponent: str | None = None,
) -> dict | None:
    """Resolve a ``(team, opponent)`` pair to one match row.

    Names are compared case-insensitively. With ``opponent`` set the lookup is
    exact; without it, returns the most recent match the team played (max
    ``match_id``) so a bare team name still works. Returns ``None`` if nothing
    matches; raises ``ValueError`` if ``team`` + ``opponent`` is ambiguous (would
    only happen if two teams meet twice, which the WC group/knockout split
    avoids).
    """
    matches = list_matches(con)
    tlow = team.lower()
    a, b = matches["team_a"].str.lower(), matches["team_b"].str.lower()
    mask = (a == tlow) | (b == tlow)
    if opponent is not None:
        olow = opponent.lower()
        mask &= (a == olow) | (b == olow)
    hit = matches[mask]
    if hit.empty:
        return None
    if opponent is not None and len(hit) > 1:
        raise ValueError(
            f"Multiple matches for {team} vs {opponent}: {hit['match_id'].tolist()}"
        )
    row = hit.iloc[-1]  # most recent if opponent omitted
    teams = [row["team_a"], row["team_b"]]
    # Put the requested team first for nicer downstream labels.
    if teams[0].lower() != tlow:
        teams = [teams[1], teams[0]]
    return {"match_id": int(row["match_id"]), "team": teams[0], "opponent": teams[1]}


def team_match_passes(
    con: duckdb.DuckDBPyConnection,
    team: str,
    match_id: int,
) -> pd.DataFrame:
    """Completed passes for ``team`` in ``match_id`` — the rows the pass network needs.

    Filters to ``type='Pass'`` with a NULL ``pass_outcome`` (StatsBomb convention
    for "completed"); excludes shootout period 5. Returns one row per pass with
    ``passer``, ``recipient``, start ``[x,y]``, end ``[x,y]``, ``minute``.
    """
    df = con.execute(
        f"""
        SELECT player AS passer,
               pass_recipient AS recipient,
               location,
               pass_end_location,
               minute,
               period
        FROM {_VIEW}
        WHERE type = 'Pass'
          AND pass_outcome IS NULL
          AND pass_recipient IS NOT NULL
          AND team = ?
          AND match_id = ?
          AND period <> {_SHOOTOUT_PERIOD}
        """,
        [team, match_id],
    ).df()
    return df


def player_metrics(con: duckdb.DuckDBPyConnection, player: str) -> dict:
    """Aggregate per-player metrics across the loaded competition.

    Returns the small set of figures the ``compare_players`` tool needs:

    - ``shots``: total shot events (excludes shootouts).
    - ``goals``: shots with outcome 'Goal'.
    - ``xg``: total StatsBomb xG over those shots.
    - ``passes_completed``: completed passes (``pass_outcome`` NULL).
    - ``key_passes``: completed passes flagged ``pass_shot_assist``.
    - ``assists``: completed passes flagged ``pass_goal_assist``.
    - ``progressive_passes``: completed passes whose end_x is >=10 yards
      closer to the opponent goal line (x=120) than the start.
    """
    row = con.execute(
        f"""
        SELECT
            SUM(CASE WHEN type='Shot' AND period<>{_SHOOTOUT_PERIOD} THEN 1 ELSE 0 END) AS shots,
            SUM(CASE WHEN type='Shot' AND shot_outcome='Goal' AND period<>{_SHOOTOUT_PERIOD} THEN 1 ELSE 0 END) AS goals,
            COALESCE(SUM(CASE WHEN type='Shot' AND period<>{_SHOOTOUT_PERIOD}
                              THEN shot_statsbomb_xg END), 0) AS xg,
            SUM(CASE WHEN type='Pass' AND pass_outcome IS NULL THEN 1 ELSE 0 END) AS passes_completed,
            SUM(CASE WHEN type='Pass' AND pass_outcome IS NULL AND pass_shot_assist=TRUE THEN 1 ELSE 0 END) AS key_passes,
            SUM(CASE WHEN type='Pass' AND pass_outcome IS NULL AND pass_goal_assist=TRUE THEN 1 ELSE 0 END) AS assists,
            SUM(CASE WHEN type='Pass' AND pass_outcome IS NULL
                          AND (pass_end_location[1] - location[1]) >= 10 THEN 1 ELSE 0 END) AS progressive_passes
        FROM {_VIEW}
        WHERE player = ?
        """,
        [player],
    ).fetchone()
    cols = ["shots","goals","xg","passes_completed","key_passes","assists","progressive_passes"]
    return {c: (float(v) if c == "xg" else int(v or 0)) for c, v in zip(cols, row)}
