"""Fivetran connector for the free-api-live-football-data RapidAPI source.

Syncs two tables to the destination:
    fixtures - all matches for the configured league
    players  - squad members for each team found in those fixtures

Run locally:  python connector.py
Deploy:       fivetran deploy
"""

import json

import requests
from fivetran_connector_sdk import Connector
from fivetran_connector_sdk import Logging as log
from fivetran_connector_sdk import Operations as op

_BASE_URL = "https://free-api-live-football-data.p.rapidapi.com"
_LEAGUE_ID = 10195

# Each squad fetch is one API call. The RapidAPI free tier allows 100/day and
# the fixtures call already burns one, so cap player syncs at 10 teams per run.
_MAX_TEAMS = 10


def schema(configuration: dict):
    return [
        {"table": "fixtures", "primary_key": ["fixture_id"]},
        {"table": "players", "primary_key": ["player_id", "team_id"]},
    ]


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
    """Flatten a raw fixture dict into a row matching the fixtures table."""
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


def update(configuration: dict, state: dict):
    hdrs = _headers(configuration)

    log.info(f"Fetching fixtures for league {_LEAGUE_ID}")
    data = _get(hdrs, "/football-get-all-matches-by-league", {"leagueid": _LEAGUE_ID})
    matches = (data.get("response") or {}).get("matches", [])
    log.info(f"Received {len(matches)} fixtures")

    for match in matches:
        op.upsert("fixtures", _map_fixture(match))

    # Checkpoint here so fixtures are durable even if the player loop fails.
    op.checkpoint(state={"step": "fixtures_done"})

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

        squad_list = (resp.get("response") or {}).get("list") or {}
        resolved_name = squad_list.get("name") or team_name
        squad_groups = squad_list.get("squad") or []

        player_count = 0
        for group in squad_groups:
            for player in group.get("members") or []:
                # Coaches share the player schema but carry this flag.
                if player.get("excludeFromRanking"):
                    continue

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

    log.info(f"Sync complete: {len(matches)} fixtures, {total_players} players")
    op.checkpoint(state={})


connector = Connector(update=update, schema=schema)


if __name__ == "__main__":
    with open("configuration.json", "r") as f:
        configuration = json.load(f)
    connector.debug(configuration=configuration)
