import json
import logging

import requests

from src.utils.bq_client import bq
from src.utils.config import config

logger = logging.getLogger(__name__)

_BASE_URL = "https://free-api-live-football-data.p.rapidapi.com"

# UEFA World Cup Qualification — has real national team data including France,
# Germany, England, Spain, Portugal. Swap to 77 when WC 2026 fixtures go live ~June 11.
# Reads from config.LEAGUE_ID (env var LEAGUE_ID, default 10195); can be overridden
# at runtime by POST /admin/switch-league which writes directly to this variable.
_WORLD_CUP_LEAGUE_ID: int = config.LEAGUE_ID

# 2022 data used for development. Swap to 2026 when provider populates WC 2026
# fixtures (~June 11 2026).
_SEASON = 2022


class FootballAPIClient:
    def __init__(self) -> None:
        self._headers = {
            "x-rapidapi-key": config.RAPIDAPI_KEY,
            "x-rapidapi-host": config.RAPIDAPI_HOST,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        url = f"{_BASE_URL}{endpoint}"
        logger.info("GET %s params=%s", url, params)
        resp = requests.get(url, headers=self._headers, params=params or {}, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Football API error: HTTP {resp.status_code} — {resp.text[:500]}"
            )
        return resp.json()

    def _table_has_any_data(self, table_name: str) -> bool:
        """Return True if the Bronze table exists and contains at least one row."""
        if not bq.table_exists(table_name):
            return False
        # Safe: table_name comes from config.table() (trusted config values only).
        rows = bq.run_query(
            f"SELECT 1 FROM `{config.table(table_name)}` LIMIT 1"
        )
        return len(rows) > 0

    def _team_squad_cached(self, team_id: int) -> bool:
        """Return True if bronze_team_squads already has rows for this team."""
        if not bq.table_exists("bronze_team_squads"):
            return False
        # Safe: team_id is int-coerced.
        rows = bq.run_query(
            f"SELECT 1 FROM `{config.table('bronze_team_squads')}` "
            f"WHERE team_id = '{int(team_id)}' LIMIT 1"
        )
        return len(rows) > 0

    def _player_detail_cached(self, player_id: int) -> bool:
        """Return True if bronze_player_details already has a row for this player."""
        if not bq.table_exists("bronze_player_details"):
            return False
        # Safe: player_id is int-coerced.
        rows = bq.run_query(
            f"SELECT 1 FROM `{config.table('bronze_player_details')}` "
            f"WHERE player_id = '{int(player_id)}' LIMIT 1"
        )
        return len(rows) > 0

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_world_cup_standings(self) -> tuple[list[dict], list[int]]:
        """Fetch standings for the configured league.

        WARNING: standings endpoint fails for international leagues. This method
        exists for future use when WC 2026 group stage data is available. Do not
        call this in the ingestion flow.

        Returns (standings_rows, team_ids).  Always unpack both.
        """
        if self._table_has_any_data("bronze_standings"):
            logger.info("Standings cache hit, reading from Bronze")
            rows = bq.run_query(f"SELECT * FROM `{config.table('bronze_standings')}`")
            # teamId field name: verify against live API response if extraction fails.
            team_ids = [int(r["teamId"]) for r in rows if r.get("teamId")]
            return rows, team_ids

        logger.info("Fetching World Cup standings from API (leagueid=%d)", _WORLD_CUP_LEAGUE_ID)
        data = self._get("/football-get-standing-all", {"leagueid": _WORLD_CUP_LEAGUE_ID})
        # standings key: verify against live API response if empty.
        standings = data.get("standings", [])
        team_ids = [int(s["teamId"]) for s in standings if s.get("teamId")]
        return standings, team_ids

    def get_world_cup_fixtures(self) -> list[dict]:
        if self._table_has_any_data("bronze_fixtures"):
            logger.info("Fixtures cache hit, reading raw_json from Bronze")
            rows = bq.run_query(f"SELECT raw_json FROM `{config.table('bronze_fixtures')}`")
            return [json.loads(r["raw_json"]) for r in rows]

        logger.info("Fetching World Cup fixtures from API (leagueid=%d)", _WORLD_CUP_LEAGUE_ID)
        data = self._get(
            "/football-get-all-matches-by-league", {"leagueid": _WORLD_CUP_LEAGUE_ID}
        )
        return data.get("response", {}).get("matches", [])

    def get_players_by_team(self, team_id: int) -> list[dict]:
        if self._team_squad_cached(team_id):
            logger.info("Players cache hit for team %d, reading raw_json from Bronze", team_id)
            rows = bq.run_query(
                f"SELECT raw_json FROM `{config.table('bronze_team_squads')}` "
                f"WHERE team_id = '{int(team_id)}'"
            )
            return [json.loads(r["raw_json"]) for r in rows]

        logger.info("Fetching players for team %d from API", team_id)
        data = self._get("/football-get-list-player", {"teamid": int(team_id)})
        # Live response: data["response"]["list"]["squad"] is a list of position groups,
        # each with a "members" list. Coaches have excludeFromRanking=True — skip them.
        squad_groups = data.get("response", {}).get("list", {}).get("squad", [])
        return [
            member
            for group in squad_groups
            for member in group.get("members", [])
            if not member.get("excludeFromRanking")
        ]

    def get_player_detail(self, player_id: int) -> dict:
        if self._player_detail_cached(player_id):
            logger.info("Player detail cache hit for player %d, reading from Bronze", player_id)
            rows = bq.run_query(
                f"SELECT * FROM `{config.table('bronze_player_details')}` "
                f"WHERE player_id = {int(player_id)} LIMIT 1"
            )
            return rows[0] if rows else {}

        logger.info("Fetching detail for player %d from API", player_id)
        data = self._get("/football-get-player-detail", {"playerid": int(player_id)})
        # player key: verify against live API response if empty.
        return data.get("player", {})

    def get_live_matches(self) -> list[dict]:
        """Fetch all currently live matches. Never cached — always fresh."""
        logger.info("Fetching live matches from API")
        data = self._get("/football-get-livescores-matches-events")
        resp = data.get("response", {})
        if isinstance(resp, list):
            return resp
        return (
            resp.get("matches")
            or resp.get("events")
            or resp.get("liveMatches")
            or []
        )

    def get_matches_by_date(self, date_str: str) -> list[dict]:
        """Fetch scheduled matches for date_str (YYYY-MM-DD). Never cached."""
        logger.info("Fetching matches for %s (leagueid=%d)", date_str, _WORLD_CUP_LEAGUE_ID)
        data = self._get(
            "/football-get-matches-by-date-and-league",
            {"leagueid": _WORLD_CUP_LEAGUE_ID, "date": date_str},
        )
        resp = data.get("response", {})
        if isinstance(resp, list):
            return resp
        return resp.get("matches") or resp.get("fixtures") or []

    def get_all_world_cup_players(self) -> list[dict]:
        """Fetch every player across all World Cup teams.

        Extracts unique team IDs from fixture home/away fields (standings endpoint
        fails for international leagues), then calls get_players_by_team() per team.
        This is the method bq_loader calls.
        """
        if self._table_has_any_data("bronze_players"):
            logger.info("All-players cache hit, reading from Bronze")
            return bq.run_query(f"SELECT * FROM `{config.table('bronze_players')}`")

        fixtures = self.get_world_cup_fixtures()
        seen: set[int] = set()
        for match in fixtures:
            for side in ("home", "away"):
                side_data = match.get(side, {})
                if isinstance(side_data, dict) and side_data.get("id"):
                    seen.add(int(side_data["id"]))
        team_ids = list(seen)
        logger.info("Fetching players for %d teams extracted from fixtures", len(team_ids))
        all_players: list[dict] = []
        for team_id in team_ids:
            all_players.extend(self.get_players_by_team(team_id))
        logger.info("Fetched %d total players", len(all_players))
        return all_players

    def get_top_scorers(self, league_id: int | None = None) -> list:
        """Fetch top goal scorers for the active league."""
        lid = league_id or _WORLD_CUP_LEAGUE_ID
        data = self._get("/football-get-top-players-by-goals", {"leagueid": lid})
        return data.get("response", {}).get("players", [])

    def get_top_assisters(self, league_id: int | None = None) -> list:
        """Fetch top assist providers for the active league."""
        lid = league_id or _WORLD_CUP_LEAGUE_ID
        data = self._get("/football-get-top-players-by-assists", {"leagueid": lid})
        return data.get("response", {}).get("players", [])

    def get_top_rated(self, league_id: int | None = None) -> list:
        """Fetch top rated players for the active league."""
        lid = league_id or _WORLD_CUP_LEAGUE_ID
        data = self._get("/football-get-top-players-by-rating", {"leagueid": lid})
        return data.get("response", {}).get("players", [])

    def get_available_leagues(self) -> list[dict]:
        """Search for World Cup leagues. Returns list of {id, name} dicts."""
        logger.info("Fetching available leagues via /football-leagues-search")
        data = self._get("/football-leagues-search", {"search": "World Cup"})
        resp = data.get("response", {})
        leagues_raw: list = []
        if isinstance(resp, list):
            leagues_raw = resp
        elif isinstance(resp, dict):
            leagues_raw = (
                resp.get("leagues")
                or resp.get("data")
                or resp.get("results")
                or []
            )
        results: list[dict] = []
        for item in leagues_raw:
            league_id = item.get("id") or item.get("leagueId") or item.get("league_id")
            name = item.get("name") or item.get("leagueName") or item.get("league_name") or ""
            if league_id is not None and name:
                results.append({"id": int(league_id), "name": str(name)})
        if not results:
            # Always include the two known league IDs as a fallback
            results = [
                {"id": 10195, "name": "FIFA World Cup Qualification UEFA"},
                {"id": 77, "name": "FIFA World Cup 2026"},
            ]
        return results


football_api = FootballAPIClient()
