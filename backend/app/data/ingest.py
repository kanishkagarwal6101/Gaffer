"""StatsBomb ingest -> Parquet cache (plan section 4).

Pulls one competition's event data via ``statsbombpy`` once
(``sb.competitions`` -> ``sb.matches`` -> ``sb.events`` per match), concatenates,
and writes ``data_cache/events.parquet``. We cache once and never hit StatsBomb
on every request.

v1 target competition (see plan section 4): FIFA World Cup 2022 —
``competition_id=43``, ``season_id=106``.

Run as a module to (re)build the cache::

    uv run python -m app.data.ingest            # build if missing
    uv run python -m app.data.ingest --refresh  # force re-pull
"""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

import pandas as pd
from statsbombpy import sb

logger = logging.getLogger(__name__)

# v1 competition: FIFA World Cup 2022.
COMPETITION_ID = 43
SEASON_ID = 106

# data_cache/ lives at the backend root: app/data/ingest.py -> backend/.
DATA_CACHE_DIR = Path(__file__).resolve().parents[2] / "data_cache"
EVENTS_PARQUET = DATA_CACHE_DIR / "events.parquet"

# Retry policy for the (rate-limited, network-bound) StatsBomb calls.
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 2.0


def _with_retries(func, *args, what: str, **kwargs):
    """Call ``func`` with simple exponential backoff, re-raising on final fail."""
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - network/parse errors vary
            last_exc = exc
            wait = _RETRY_BACKOFF_SECONDS * attempt
            logger.warning(
                "Fetch failed (%s), attempt %d/%d: %s. Retrying in %.1fs",
                what,
                attempt,
                _MAX_RETRIES,
                exc,
                wait,
            )
            time.sleep(wait)
    assert last_exc is not None
    raise RuntimeError(f"Giving up on {what} after {_MAX_RETRIES} attempts") from last_exc


def fetch_matches(competition_id: int = COMPETITION_ID, season_id: int = SEASON_ID) -> pd.DataFrame:
    """Return all matches for the competition/season."""
    matches = _with_retries(
        sb.matches,
        competition_id=competition_id,
        season_id=season_id,
        what="sb.matches",
    )
    logger.info("Fetched %d matches for competition=%s season=%s", len(matches), competition_id, season_id)
    return matches


def fetch_all_events(match_ids: list[int]) -> pd.DataFrame:
    """Fetch and concatenate events for every match id, tagging each row with ``match_id``."""
    frames: list[pd.DataFrame] = []
    total = len(match_ids)
    for i, match_id in enumerate(match_ids, start=1):
        events = _with_retries(sb.events, int(match_id), what=f"sb.events(match_id={match_id})")
        if "match_id" not in events.columns:
            events["match_id"] = int(match_id)
        frames.append(events)
        logger.info("[%d/%d] match_id=%s -> %d events", i, total, match_id, len(events))

    if not frames:
        raise RuntimeError("No events fetched; cannot build cache")

    combined = pd.concat(frames, ignore_index=True)
    logger.info("Concatenated %d events across %d matches", len(combined), total)
    return combined


def _coerce_object_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Make the frame parquet-friendly.

    StatsBomb events carry nested values (lists/dicts) like ``location`` and
    ``shot_freeze_frame``. pyarrow cannot infer a stable type for mixed/object
    columns, so we stringify any column it can't serialize natively.
    """
    df = df.copy()
    for col in df.columns:
        sample = df[col].dropna()
        if sample.empty:
            continue
        if sample.map(lambda v: isinstance(v, (list, dict))).any():
            df[col] = df[col].apply(lambda v: None if v is None else repr(v))
    return df


def ingest(refresh: bool = False) -> Path:
    """Build ``data_cache/events.parquet`` (idempotent unless ``refresh``).

    Returns the path to the parquet file.
    """
    DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if EVENTS_PARQUET.exists() and not refresh:
        logger.info("Cache already present at %s (use refresh=True to rebuild)", EVENTS_PARQUET)
        return EVENTS_PARQUET

    matches = fetch_matches()
    match_ids = [int(m) for m in matches["match_id"].tolist()]
    events = fetch_all_events(match_ids)

    try:
        events.to_parquet(EVENTS_PARQUET, index=False)
    except Exception as exc:  # noqa: BLE001 - fall back to stringifying nested columns
        logger.warning("Direct parquet write failed (%s); coercing nested columns", exc)
        _coerce_object_columns(events).to_parquet(EVENTS_PARQUET, index=False)

    logger.info("Wrote %d events to %s", len(events), EVENTS_PARQUET)
    return EVENTS_PARQUET


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest StatsBomb events into the Parquet cache")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Force a re-pull even if the cache already exists",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _parse_args(argv)
    path = ingest(refresh=args.refresh)
    print(f"Events cache ready at: {path}")


if __name__ == "__main__":
    main()
