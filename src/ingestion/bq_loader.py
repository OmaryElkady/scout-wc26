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

def _map_fixture(raw: dict, ts: str, league_id: int) -> dict:
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
        "league_id": str(league_id),
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


def _map_squad_member_to_bronze_players(raw: dict, team_id: int, team_name: str, ts: str) -> dict:
    """Map a squad member to the bronze_players schema (used by silver_players.sql)."""
    age_raw = raw.get("age")
    shirt_raw = raw.get("shirtNumber")
    return {
        "player_id": str(raw.get("id", "")),
        "team_id": str(team_id),
        "team_name": team_name,
        "name": raw.get("name", ""),
        "position": raw.get("positionIdsDesc", ""),
        "nationality": team_name,  # squad members represent the national team
        "age": int(age_raw) if age_raw is not None else None,
        "jersey_number": int(shirt_raw) if shirt_raw is not None else None,
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


def write_bronze_fixtures(rows: list[dict], league_id: int | None = None) -> None:
    """Write fixture rows to bronze_fixtures, tagged with the explicit league_id.

    league_id MUST be the league we actually fetched the fixtures for —
    do NOT rely on the module-level _WORLD_CUP_LEAGUE_ID at write time,
    because it may have been swapped between fetch and write (e.g. when
    a stale cache returns fixtures from a previous league). Defaults to
    _WORLD_CUP_LEAGUE_ID for backwards compatibility with callers that
    have not been updated yet, but emits a warning when used.
    """
    if not rows:
        logger.warning("write_bronze_fixtures called with no rows, skipping")
        return
    if league_id is None:
        logger.warning(
            "write_bronze_fixtures called without league_id — falling back to "
            "_WORLD_CUP_LEAGUE_ID=%d. This can mis-tag fixtures across leagues.",
            _WORLD_CUP_LEAGUE_ID,
        )
        league_id = _WORLD_CUP_LEAGUE_ID
    ts = _now()
    mapped = [_map_fixture(r, ts, league_id) for r in rows]
    logger.info(
        "Writing %d rows to bronze_fixtures (league_id=%d)", len(mapped), league_id
    )
    bq.insert_rows("bronze_fixtures", mapped)


def write_bronze_standings(rows: list[dict]) -> None:
    if not rows:
        logger.warning("write_bronze_standings called with no rows, skipping")
        return
    ts = _now()
    stamped = [{**row, "ingested_at": ts, "source": _SOURCE} for row in rows]
    logger.info("Writing %d rows to bronze_standings", len(stamped))
    bq.insert_rows("bronze_standings", stamped)


def write_bronze_top_performers(scorers: list, assisters: list, rated: list) -> None:
    """Write top scorers, assisters, and rated players to bronze_top_performers.

    Rows from all three lists are merged into a single table keyed by player_id + stat_type.
    """
    ts = _now()
    rows: list[dict] = []
    for p in scorers:
        rows.append({
            "player_id": str(p.get("id", "")),
            "player_name": p.get("name", ""),
            "team_id": str(p.get("teamId", "")),
            "team_name": p.get("teamName", ""),
            "goals": p.get("goals", 0),
            "assists": None,
            "rating": None,
            "stat_type": "goals",
            "ingested_at": ts,
            "source": _SOURCE,
        })
    for p in assisters:
        rows.append({
            "player_id": str(p.get("id", "")),
            "player_name": p.get("name", ""),
            "team_id": str(p.get("teamId", "")),
            "team_name": p.get("teamName", ""),
            "goals": None,
            "assists": p.get("assists", 0),
            "rating": None,
            "stat_type": "assists",
            "ingested_at": ts,
            "source": _SOURCE,
        })
    for p in rated:
        rows.append({
            "player_id": str(p.get("id", "")),
            "player_name": p.get("name", ""),
            "team_id": str(p.get("teamId", "")),
            "team_name": p.get("teamName", ""),
            "goals": None,
            "assists": None,
            "rating": p.get("rating"),
            "stat_type": "rating",
            "ingested_at": ts,
            "source": _SOURCE,
        })
    if not rows:
        logger.warning("write_bronze_top_performers: no rows to write, skipping")
        return
    logger.info("Writing %d rows to bronze_top_performers", len(rows))
    bq.insert_rows("bronze_top_performers", rows)


def write_bronze_team_squads(team_id: int, rows: list[dict], team_name: str = "") -> None:
    if not rows:
        logger.warning("write_bronze_team_squads called with no rows for team %d, skipping", team_id)
        return
    ts = _now()
    compact = [_map_squad_member(r, team_id, team_name, ts) for r in rows]
    logger.info("Writing %d rows to bronze_team_squads for team %d", len(compact), team_id)
    bq.insert_rows("bronze_team_squads", compact)
    full = [_map_squad_member_to_bronze_players(r, team_id, team_name, ts) for r in rows]
    logger.info("Writing %d rows to bronze_players for team %d", len(full), team_id)
    bq.insert_rows("bronze_players", full)
