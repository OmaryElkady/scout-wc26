"""Fivetran connector for free-api-live-football-data — World Cup 2026 qualification.

Syncs two tables:
  fixtures  — all matches for league 10195 (UEFA WC Qualification)
  players   — squad members for each team found in those fixtures

Run locally:  fivetran debug
Deploy:       fivetran deploy
"""

import json

import requests
from fivetran_connector_sdk import Connector
from fivetran_connector_sdk import Logging as log
from fivetran_connector_sdk import Operations as op

_BASE_URL = "https://free-api-live-football-data.p.rapidapi.com"
_LEAGUE_ID = 10195

# Each team squad costs one API call. Free tier allows 100 req/day; fixtures
# already consumes one, so cap player syncs at 10 teams per run.
_MAX_TEAMS = 10


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def schema(configuration: dict):
    """Declare tables and primary keys. Column types inferred from upserted data."""
    return [
        {
            "table": "fixtures",
            "primary_key": ["fixture_id"],
        },
        {
            "table": "players",
            "primary_key": ["player_id", "team_id"],
        },
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _headers(configuration: dict) -> dict:
    return {
        "x-rapidapi-key": configuration["rapidapi_key"],
        "x-rapidapi-host": configuration["rapidapi_host"],
    }


def _get(headers: dict, endpoint: str, params: dict | None = None) -> dict:
    url = f"{_BASE_URL}{endpoint}"
    log.debug(f"GET {url} params={params}")
    resp = requests.get(url, headers=headers, params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _map_fixture(match: dict) -> dict:
    """Flatten a raw fixture dict to the fixtures table schema.

    Confirmed live field paths from football_api.py / bq_loader._map_fixture():
      home/away contain: id, name, score
      status contains:   utcTime, reason.short
    """
    home = match.get("home") or {}
    away = match.get("away") or {}
    status = match.get("status") or {}
    home_score = home.get("score")
    away_score = away.get("score")
    return {
        "fixture_id": str(match.get("id", "")),
        "home_team_id": str(home.get("id", "")),
        "home_team_name": home.get("name", ""),
        "away_team_id": str(away.get("id", "")),
        "away_team_name": away.get("name", ""),
        "match_date": status.get("utcTime", ""),
        "status": (status.get("reason") or {}).get("short", ""),
        "home_score": int(home_score) if home_score is not None else None,
        "away_score": int(away_score) if away_score is not None else None,
        "league_id": str(_LEAGUE_ID),
    }


def _teams_from_matches(matches: list) -> dict[str, str]:
    """Return {team_id: team_name} for every team appearing in fixtures."""
    teams: dict[str, str] = {}
    for match in matches:
        for side in ("home", "away"):
            side_data = match.get(side) or {}
            tid = str(side_data.get("id", ""))
            if tid and tid not in teams:
                teams[tid] = side_data.get("name", tid)
    return teams


# ---------------------------------------------------------------------------
# Update (called by Fivetran on every sync)
# ---------------------------------------------------------------------------

def update(configuration: dict, state: dict):
    """Sync fixtures then squad data. Uses direct op.upsert() — no yield needed."""
    hdrs = _headers(configuration)

    # ── Step 1: Fixtures ─────────────────────────────────────────────────────
    log.info(f"Fetching fixtures for league {_LEAGUE_ID}")
    data = _get(hdrs, "/football-get-all-matches-by-league", {"leagueid": _LEAGUE_ID})
    matches = (data.get("response") or {}).get("matches", [])
    log.info(f"Received {len(matches)} fixtures")

    for match in matches:
        op.upsert("fixtures", _map_fixture(match))

    # Checkpoint after fixtures so Fivetran can safely write if players fail.
    op.checkpoint(state={"step": "fixtures_done"})

    # ── Step 2: Players ──────────────────────────────────────────────────────
    teams = _teams_from_matches(matches)
    team_sample = list(teams.items())[:_MAX_TEAMS]
    log.info(f"Syncing players for {len(team_sample)} of {len(teams)} teams (cap={_MAX_TEAMS})")

    total_players = 0
    for team_id, team_name in team_sample:
        try:
            resp = _get(hdrs, "/football-get-list-player", {"teamid": team_id})
        except requests.HTTPError as exc:
            log.warning(f"Squad fetch failed for team {team_id} ({team_name}): {exc}")
            continue

        # Confirmed response path: response.list.squad (list of position groups)
        # response.list.name is the canonical team name from the squad endpoint.
        squad_list = (resp.get("response") or {}).get("list") or {}
        resolved_name = squad_list.get("name") or team_name
        squad_groups = squad_list.get("squad") or []

        player_count = 0
        for group in squad_groups:
            for player in group.get("members") or []:
                if player.get("excludeFromRanking"):
                    continue  # coaches have this flag set; skip them

                age_raw = player.get("age")
                shirt_raw = player.get("shirtNumber")
                op.upsert("players", {
                    "player_id": str(player.get("id", "")),
                    "team_id": team_id,
                    "team_name": resolved_name,
                    "name": player.get("name", ""),
                    "position": player.get("positionIdsDesc", ""),
                    "age": int(age_raw) if age_raw is not None else None,
                    "jersey_number": int(shirt_raw) if shirt_raw is not None else None,
                })
                player_count += 1

        total_players += player_count
        log.info(f"  {resolved_name}: {player_count} players")

    log.info(f"Sync complete — {len(matches)} fixtures, {total_players} players")
    op.checkpoint(state={})


# ---------------------------------------------------------------------------
# Connector entry point
# ---------------------------------------------------------------------------

connector = Connector(update=update, schema=schema)

if __name__ == "__main__":
    with open("configuration.json", "r") as f:
        configuration = json.load(f)
    connector.debug(configuration=configuration)
