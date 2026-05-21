import logging

import requests

from src.utils.bq_client import bq
from src.utils.config import config

logger = logging.getLogger(__name__)

_BASE_URL = "https://free-api-live-football-data.p.rapidapi.com"

# Confirmed via live API search (/football-leagues-search?search=World%20Cup).
_WORLD_CUP_LEAGUE_ID = 77


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
            f"WHERE team_id = {int(team_id)} LIMIT 1"
        )
        return len(rows) > 0

    def _player_detail_cached(self, player_id: int) -> bool:
        """Return True if bronze_player_details already has a row for this player."""
        if not bq.table_exists("bronze_player_details"):
            return False
        # Safe: player_id is int-coerced.
        rows = bq.run_query(
            f"SELECT 1 FROM `{config.table('bronze_player_details')}` "
            f"WHERE player_id = {int(player_id)} LIMIT 1"
        )
        return len(rows) > 0

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_world_cup_standings(self) -> tuple[list[dict], list[int]]:
        """Fetch standings for league 77 and extract team IDs for downstream calls.

        Returns (standings_rows, team_ids).  Always unpack both — callers need
        team_ids to drive get_all_world_cup_players().
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
            logger.info("Fixtures cache hit, reading from Bronze")
            return bq.run_query(f"SELECT * FROM `{config.table('bronze_fixtures')}`")

        logger.info("Fetching World Cup fixtures from API (leagueid=%d)", _WORLD_CUP_LEAGUE_ID)
        data = self._get(
            "/football-get-all-matches-by-league", {"leagueid": _WORLD_CUP_LEAGUE_ID}
        )
        return data.get("matches", [])

    def get_players_by_team(self, team_id: int) -> list[dict]:
        if self._team_squad_cached(team_id):
            logger.info("Players cache hit for team %d, reading from Bronze", team_id)
            return bq.run_query(
                f"SELECT * FROM `{config.table('bronze_team_squads')}` "
                f"WHERE team_id = {int(team_id)}"
            )

        logger.info("Fetching players for team %d from API", team_id)
        data = self._get("/football-get-list-player", {"teamid": int(team_id)})
        # players key: verify against live API response if empty.
        return data.get("players", [])

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

    def get_all_world_cup_players(self) -> list[dict]:
        """Fetch every player across all World Cup teams.

        Calls get_world_cup_standings() to get team IDs, then
        get_players_by_team() per team.  This is the method bq_loader calls.
        """
        if self._table_has_any_data("bronze_players"):
            logger.info("All-players cache hit, reading from Bronze")
            return bq.run_query(f"SELECT * FROM `{config.table('bronze_players')}`")

        _, team_ids = self.get_world_cup_standings()
        logger.info("Fetching players for %d teams", len(team_ids))
        all_players: list[dict] = []
        for team_id in team_ids:
            all_players.extend(self.get_players_by_team(team_id))
        logger.info("Fetched %d total players", len(all_players))
        return all_players


football_api = FootballAPIClient()
