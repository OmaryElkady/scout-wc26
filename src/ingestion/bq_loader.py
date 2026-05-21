import json
import logging
from datetime import datetime, timezone

from src.utils.bq_client import bq
from src.utils.football_api import _WORLD_CUP_LEAGUE_ID, _SEASON

logger = logging.getLogger(__name__)

_SOURCE = "free-api-live-football-data"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Row mappers — raw API dict → Bronze schema fields
# ---------------------------------------------------------------------------

def _map_fixture(raw: dict, ts: str) -> dict:
    home = raw.get("home", {})
    away = raw.get("away", {})
    status = raw.get("status", {})
    home_score = home.get("score")
    away_score = away.get("score")
    return {
        "fixture_id": str(raw.get("id", "")),
        "home_team_id": str(home.get("id", "")),
        "home_team_name": home.get("name", ""),
        "away_team_id": str(away.get("id", "")),
        "away_team_name": away.get("name", ""),
        "match_date": status.get("utcTime", ""),
        "status": status.get("reason", {}).get("short", ""),
        "home_score": int(home_score) if home_score is not None else None,
        "away_score": int(away_score) if away_score is not None else None,
        "league_id": str(_WORLD_CUP_LEAGUE_ID),
        "season": _SEASON,
        "raw_json": json.dumps(raw),
        "ingested_at": ts,
        "source": _SOURCE,
    }


def _map_squad_member(raw: dict, team_id: int, team_name: str, ts: str) -> dict:
    return {
        "team_id": str(team_id),
        "team_name": team_name,
        "player_id": str(raw.get("id", "")),
        "player_name": raw.get("name", ""),
        "position": raw.get("positionIdsDesc", ""),
        "raw_json": json.dumps(raw),
        "ingested_at": ts,
        "source": _SOURCE,
    }


# ---------------------------------------------------------------------------
# Public write functions
# ---------------------------------------------------------------------------

def write_bronze_players(rows: list[dict]) -> None:
    if not rows:
        logger.warning("write_bronze_players called with no rows, skipping")
        return
    ts = _now()
    stamped = [{**row, "ingested_at": ts, "source": _SOURCE} for row in rows]
    logger.info("Writing %d rows to bronze_players", len(stamped))
    bq.insert_rows("bronze_players", stamped)


def write_bronze_fixtures(rows: list[dict]) -> None:
    if not rows:
        logger.warning("write_bronze_fixtures called with no rows, skipping")
        return
    ts = _now()
    mapped = [_map_fixture(r, ts) for r in rows]
    logger.info("Writing %d rows to bronze_fixtures", len(mapped))
    bq.insert_rows("bronze_fixtures", mapped)


def write_bronze_standings(rows: list[dict]) -> None:
    if not rows:
        logger.warning("write_bronze_standings called with no rows, skipping")
        return
    ts = _now()
    stamped = [{**row, "ingested_at": ts, "source": _SOURCE} for row in rows]
    logger.info("Writing %d rows to bronze_standings", len(stamped))
    bq.insert_rows("bronze_standings", stamped)


def write_bronze_team_squads(team_id: int, rows: list[dict], team_name: str = "") -> None:
    if not rows:
        logger.warning("write_bronze_team_squads called with no rows for team %d, skipping", team_id)
        return
    ts = _now()
    mapped = [_map_squad_member(r, team_id, team_name, ts) for r in rows]
    logger.info("Writing %d rows to bronze_team_squads for team %d", len(mapped), team_id)
    bq.insert_rows("bronze_team_squads", mapped)
