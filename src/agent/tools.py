import logging
from typing import Any, Optional

from src.utils.bq_client import bq
from src.utils.config import config

logger = logging.getLogger(__name__)

_MAX_RESULTS = 20


def _esc(value: str) -> str:
    """Escape single quotes for BigQuery string literals."""
    return value.replace("'", "''")


def query_players(
    position: Optional[str] = None,
    nationality: Optional[str] = None,
    team_name: Optional[str] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Search the gold_player_stats table for players matching optional filters.

    All parameters are optional; omit any to return players without that filter (up to 20).
    Use this tool when the user asks about players by position, country, team, or age range.

    Parameters
    ----------
    position : str, optional
        Player position to filter by. Accepted values: 'Goalkeeper', 'Defender',
        'Midfielder', 'Forward'. Comparison is case-insensitive.
    nationality : str, optional
        Nationality or country name substring (partial match, case-insensitive).
        E.g. 'French', 'Brazil', 'England'.
    team_name : str, optional
        Club or national team name substring (partial match, case-insensitive).
        E.g. 'France', 'Real Madrid', 'Manchester'.
    min_age : int, optional
        Minimum player age (inclusive).
    max_age : int, optional
        Maximum player age (inclusive).

    Returns
    -------
    list of dict
        Up to 20 player records. Each dict contains: player_id, name, team_id,
        team_name, position, nationality, age, jersey_number, league_id.
        Returns an empty list if no players match the filters.
    """
    table = config.table("gold_player_stats")
    conditions = []

    if position:
        conditions.append("LOWER(position) = LOWER('" + _esc(position) + "')")
    if nationality:
        conditions.append("LOWER(nationality) LIKE '%" + _esc(nationality.lower()) + "%'")
    if team_name:
        conditions.append("LOWER(team_name) LIKE '%" + _esc(team_name.lower()) + "%'")
    if min_age is not None:
        conditions.append("age >= " + str(int(min_age)))
    if max_age is not None:
        conditions.append("age <= " + str(int(max_age)))

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = "SELECT * FROM `" + table + "` " + where + " LIMIT " + str(_MAX_RESULTS)

    logger.info(
        "query_players: position=%s nationality=%s team=%s age=[%s,%s]",
        position,
        nationality,
        team_name,
        min_age,
        max_age,
    )
    rows = bq.run_query(sql)
    logger.info("query_players: returned %d rows", len(rows))
    return rows


def query_team_summary(
    team_name: Optional[str] = None,
    team_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Look up a team's match record from the gold_team_summary table.

    Returns aggregated statistics: wins, draws, losses, goals for/against,
    goal difference, and total points (3 per win, 1 per draw), computed only
    from completed matches. Use this when the user asks how a team is performing,
    their points total, or how many goals they have scored/conceded.

    Parameters
    ----------
    team_name : str, optional
        Team name substring (partial match, case-insensitive). E.g. 'France', 'Brazil'.
        Use when the user provides a team name.
    team_id : str, optional
        Exact BigQuery team_id string (e.g. '3378'). Use when you already know the
        team ID from a previous query_players or get_player_detail call.

    Returns
    -------
    dict
        Team record with keys: team_id, team_name, matches_played, wins, draws,
        losses, goals_for, goals_against, goal_difference, points.
        Returns an empty dict if the team is not found.
    """
    table = config.table("gold_team_summary")
    conditions = []

    if team_id is not None:
        conditions.append("team_id = '" + _esc(str(team_id)) + "'")
    if team_name:
        conditions.append("LOWER(team_name) LIKE '%" + _esc(team_name.lower()) + "%'")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    sql = "SELECT * FROM `" + table + "` " + where + " LIMIT 1"

    logger.info("query_team_summary: team_name=%s team_id=%s", team_name, team_id)
    rows = bq.run_query(sql)
    logger.info("query_team_summary: found=%s", bool(rows))
    return rows[0] if rows else {}


def get_player_detail(
    player_name: Optional[str] = None,
    player_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Retrieve the full profile for a single player from gold_player_stats.

    Use this when the user asks about a specific named player, or before
    generating a scouting report. Prefer player_id for an exact lookup;
    use player_name for name-based search (partial match, case-insensitive).

    Parameters
    ----------
    player_name : str, optional
        Player name substring (partial match, case-insensitive).
        E.g. 'Mbappe', 'Kylian Mbappé', 'vinicius'.
    player_id : str, optional
        Exact BigQuery player_id string. Use for deterministic lookup when
        you already know the player ID from a previous query result.

    Returns
    -------
    dict
        Full player profile with keys: player_id, name, team_id, team_name,
        position, nationality, age, jersey_number, league_id.
        Returns an empty dict if the player is not found.
    """
    table = config.table("gold_player_stats")
    conditions = []

    if player_id is not None:
        conditions.append("player_id = '" + _esc(str(player_id)) + "'")
    if player_name:
        conditions.append("LOWER(name) LIKE '%" + _esc(player_name.lower()) + "%'")

    if not conditions:
        logger.warning("get_player_detail called with no filters — returning empty")
        return {}

    where = "WHERE " + " AND ".join(conditions)
    sql = "SELECT * FROM `" + table + "` " + where + " LIMIT 1"

    logger.info("get_player_detail: player_name=%s player_id=%s", player_name, player_id)
    rows = bq.run_query(sql)
    return rows[0] if rows else {}


def get_top_players_by_position(
    position: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """
    Return the youngest players for a given position, ordered by age ascending.

    Age ascending is used as a proxy for future potential — younger players
    have more career years ahead and are typically higher-value scouting targets.
    Use this when the user asks for young prospects, top talent by position,
    or wants to know who to watch for the future of a specific role.

    Parameters
    ----------
    position : str
        Player position to filter. Accepted values: 'Goalkeeper', 'Defender',
        'Midfielder', 'Forward'. Comparison is case-insensitive.
    limit : int, optional
        Maximum number of players to return. Defaults to 10. Capped at 100.

    Returns
    -------
    list of dict
        Up to `limit` player records ordered by age ascending (youngest first).
        Each dict contains: player_id, name, team_id, team_name, position,
        nationality, age, jersey_number, league_id.
        Returns an empty list if no players match the position.
    """
    table = config.table("gold_player_stats")
    safe_limit = str(max(1, min(int(limit), 100)))
    sql = (
        "SELECT * FROM `"
        + table
        + "` WHERE LOWER(position) = LOWER('"
        + _esc(position)
        + "') ORDER BY age ASC LIMIT "
        + safe_limit
    )

    logger.info("get_top_players_by_position: position=%s limit=%s", position, limit)
    rows = bq.run_query(sql)
    logger.info("get_top_players_by_position: returned %d rows", len(rows))
    return rows
