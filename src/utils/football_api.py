import logging

import requests

from src.utils.bq_client import bq
from src.utils.config import config

logger = logging.getLogger(__name__)

_BASE_URL = "https://free-api-live-football-data.p.rapidapi.com"

# FIFA World Cup competition ID in Free API Live Football Data.
# Update this constant if the provider changes the ID.
_WORLD_CUP_COMPETITION_ID = 17


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

    def _bronze_has_data(self, bronze_table: str, season: int) -> bool:
        """Return True if Bronze already holds data for this table/season.

        Both inputs are trusted (table from config.table(), season is int-coerced),
        so the inline format string is safe against injection.
        """
        if not bq.table_exists(bronze_table):
            return False
        rows = bq.run_query(
            f"SELECT 1 FROM `{config.table(bronze_table)}` "
            f"WHERE season = {int(season)} LIMIT 1"
        )
        return len(rows) > 0

    def _read_bronze(self, bronze_table: str, season: int) -> list[dict]:
        return bq.run_query(
            f"SELECT * FROM `{config.table(bronze_table)}` "
            f"WHERE season = {int(season)}"
        )

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    def get_world_cup_players(self, season: int = 2026) -> list[dict]:
        if self._bronze_has_data("bronze_players", season):
            logger.info("Players cache hit (season=%d), reading from Bronze", season)
            return self._read_bronze("bronze_players", season)
        logger.info("Fetching World Cup players from API (season=%d)", season)
        data = self._get(
            "/football-get-all-players-by-competition-season",
            {"compId": _WORLD_CUP_COMPETITION_ID, "season": season},
        )
        return data.get("response", [])

    def get_world_cup_fixtures(self, season: int = 2026) -> list[dict]:
        if self._bronze_has_data("bronze_fixtures", season):
            logger.info("Fixtures cache hit (season=%d), reading from Bronze", season)
            return self._read_bronze("bronze_fixtures", season)
        logger.info("Fetching World Cup fixtures from API (season=%d)", season)
        data = self._get(
            "/football-get-all-fixtures-by-competition-season",
            {"compId": _WORLD_CUP_COMPETITION_ID, "season": season},
        )
        return data.get("response", [])

    def get_world_cup_standings(self, season: int = 2026) -> list[dict]:
        if self._bronze_has_data("bronze_standings", season):
            logger.info("Standings cache hit (season=%d), reading from Bronze", season)
            return self._read_bronze("bronze_standings", season)
        logger.info("Fetching World Cup standings from API (season=%d)", season)
        data = self._get(
            "/football-get-standings-by-competition-season",
            {"compId": _WORLD_CUP_COMPETITION_ID, "season": season},
        )
        return data.get("response", [])


football_api = FootballAPIClient()
