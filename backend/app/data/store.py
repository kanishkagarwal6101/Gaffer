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
    return {row[0] for row in con.execute(f"PRAGMA table_info('{_VIEW}')").fetchall()}


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
    params.append(limit)
    return con.execute(f"SELECT * FROM {_VIEW} {where} LIMIT ?", params).df()


def player_shots(con: duckdb.DuckDBPyConnection, player: str) -> pd.DataFrame:
    """Return all shot events for a player, with xG and outcome."""
    cols = _columns(con)
    select = ["player", "team", "type", "shot_outcome", "shot_statsbomb_xg", "location", "match_id"]
    select = [c for c in select if c in cols]
    return con.execute(
        f"SELECT {', '.join(select)} FROM {_VIEW} WHERE type = 'Shot' AND player = ?",
        [player],
    ).df()


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
