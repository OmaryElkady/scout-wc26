import logging
from datetime import datetime, timezone

from src.utils.bq_client import bq

logger = logging.getLogger(__name__)

_SOURCE = "free-api-live-football-data"


def _stamp(rows: list[dict]) -> list[dict]:
    """Return new row dicts with ingested_at and source appended; originals are not mutated."""
    ts = datetime.now(timezone.utc).isoformat()
    return [{**row, "ingested_at": ts, "source": _SOURCE} for row in rows]


def write_bronze_players(rows: list[dict]) -> None:
    if not rows:
        logger.warning("write_bronze_players called with no rows, skipping")
        return
    stamped = _stamp(rows)
    logger.info("Writing %d rows to bronze_players", len(stamped))
    bq.insert_rows("bronze_players", stamped)


def write_bronze_fixtures(rows: list[dict]) -> None:
    if not rows:
        logger.warning("write_bronze_fixtures called with no rows, skipping")
        return
    stamped = _stamp(rows)
    logger.info("Writing %d rows to bronze_fixtures", len(stamped))
    bq.insert_rows("bronze_fixtures", stamped)


def write_bronze_standings(rows: list[dict]) -> None:
    if not rows:
        logger.warning("write_bronze_standings called with no rows, skipping")
        return
    stamped = _stamp(rows)
    logger.info("Writing %d rows to bronze_standings", len(stamped))
    bq.insert_rows("bronze_standings", stamped)
