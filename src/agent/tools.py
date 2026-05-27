import logging
from typing import Any, Optional

from src.utils.bq_client import bq
from src.utils.config import config
from src.utils.progress import emit_progress

logger = logging.getLogger(__name__)

_MAX_RESULTS = 20

# Silver transform normalises positions to these four codes.
_POSITION_MAP: dict[str, str] = {
    "goalkeeper": "GK",
    "goalkeepers": "GK",
    "gk": "GK",
    "defender": "DEF",
    "defenders": "DEF",
    "def": "DEF",
    "back": "DEF",
    "midfielder": "MID",
    "midfielders": "MID",
    "mid": "MID",
    "midfield": "MID",
    "forward": "FWD",
    "forwards": "FWD",
    "fwd": "FWD",
    "attacker": "FWD",
    "attackers": "FWD",
    "striker": "FWD",
    "strikers": "FWD",
    "winger": "FWD",
}


def _normalize_position(pos: str) -> str:
    """Translate a natural-language position name to the stored abbreviation."""
    return _POSITION_MAP.get(pos.strip().lower(), pos.upper())


def _esc(value: str) -> str:
    """Escape single quotes for BigQuery string literals."""
    return value.replace("'", "''")


def _get_active_league_id() -> str:
    """Return the current active league ID as a string for BigQuery STRING comparisons."""
    import src.utils.football_api as _fa_mod

    return str(_fa_mod._WORLD_CUP_LEAGUE_ID)


def query_players(
    position: Optional[str] = None,
    nationality: Optional[str] = None,
    team_name: Optional[str] = None,
    min_age: Optional[int] = None,
    max_age: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Search the gold_player_stats table for players matching optional filters.

    When called with no arguments, returns a sample of up to 20 players spread
    across all teams (ordered by team name then player name). When filters are
    provided, returns only players matching all supplied criteria (up to 20).
    Use this tool when the user asks about players by position, country, team, or age range.

    Parameters
    ----------
    position : str, optional
        Player position to filter by. Stored values are 'GK' (goalkeeper),
        'DEF' (defender), 'MID' (midfielder), 'FWD' (forward). Common words
        like 'Goalkeeper', 'Midfielder', 'Forward' are also accepted and will
        be normalised automatically.
    nationality : str, optional
        Nationality or country name substring (partial match, case-insensitive).
        E.g. 'Germany', 'Luxembourg', 'Northern Ireland'.
    team_name : str, optional
        National team name substring (partial match, case-insensitive).
        E.g. 'Germany', 'Slovakia', 'Luxembourg'.
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
    conditions = ["league_id = '" + _esc(_get_active_league_id()) + "'"]

    if position:
        conditions.append("position = '" + _esc(_normalize_position(position)) + "'")
    if nationality:
        conditions.append("LOWER(nationality) LIKE '%" + _esc(nationality.lower()) + "%'")
    if team_name:
        conditions.append("LOWER(team_name) LIKE '%" + _esc(team_name.lower()) + "%'")
    if min_age is not None:
        conditions.append("age >= " + str(int(min_age)))
    if max_age is not None:
        conditions.append("age <= " + str(int(max_age)))

    where = "WHERE " + " AND ".join(conditions)
    order_by = " ORDER BY team_name, name"
    sql = "SELECT * FROM `" + table + "` " + where + order_by + " LIMIT " + str(_MAX_RESULTS)

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
) -> Any:
    """
    Get team performance summary. Call with no arguments to get all teams ranked
    by points. Call with team_name to get a specific team.

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
    list of dict (no arguments)
        All teams ordered by points descending (up to 20). Each dict contains:
        team_id, team_name, matches_played, wins, draws, losses, goals_for,
        goals_against, goal_difference, points.
    dict (team_name or team_id supplied)
        Single team record. Returns an empty dict if the team is not found.
    """
    table = config.table("gold_team_summary")
    league_filter = "league_id = '" + _esc(_get_active_league_id()) + "'"
    conditions = []

    if team_id is not None:
        conditions.append("team_id = '" + _esc(str(team_id)) + "'")
    if team_name:
        conditions.append("LOWER(team_name) LIKE '%" + _esc(team_name.lower()) + "%'")

    logger.info("query_team_summary: team_name=%s team_id=%s", team_name, team_id)

    if conditions:
        where = "WHERE " + league_filter + " AND " + " AND ".join(conditions)
        sql = "SELECT * FROM `" + table + "` " + where + " LIMIT 1"
        rows = bq.run_query(sql)
        logger.info("query_team_summary: found=%s", bool(rows))
        return rows[0] if rows else {}

    sql = "SELECT * FROM `" + table + "` WHERE " + league_filter + " ORDER BY points DESC LIMIT " + str(_MAX_RESULTS)
    rows = bq.run_query(sql)
    logger.info("query_team_summary: returned %d teams", len(rows))
    return rows


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
    conditions = ["league_id = '" + _esc(_get_active_league_id()) + "'"]

    if player_id is not None:
        conditions.append("player_id = '" + _esc(str(player_id)) + "'")
    if player_name:
        conditions.append("LOWER(name) LIKE '%" + _esc(player_name.lower()) + "%'")

    if len(conditions) == 1:
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
        Player position to filter. Stored values are 'GK', 'DEF', 'MID', 'FWD'.
        Common words like 'Goalkeeper', 'Midfielder', 'Forward' are also accepted
        and will be normalised automatically.
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
        + "` WHERE league_id = '"
        + _esc(_get_active_league_id())
        + "' AND position = '"
        + _esc(_normalize_position(position))
        + "' ORDER BY age ASC LIMIT "
        + safe_limit
    )

    logger.info("get_top_players_by_position: position=%s limit=%s", position, limit)
    rows = bq.run_query(sql)
    logger.info("get_top_players_by_position: returned %d rows", len(rows))
    return rows


def get_team_roster(team_name: str) -> list[dict[str, Any]]:
    """
    Get the full roster of players for a specific team. Returns all players with
    their position, age, and nationality. Use this when asked about a team's squad,
    lineup, or players.

    Parameters
    ----------
    team_name : str
        Team name to look up (partial match, case-insensitive). E.g. 'Germany', 'France'.

    Returns
    -------
    list of dict
        All players for the team ordered by position then name. Each dict contains:
        player_id, name, position, age, nationality, jersey_number.
        Returns an empty list if the team is not found.
    """
    table = config.table("gold_player_stats")
    sql = (
        "SELECT player_id, name, position, age, nationality, jersey_number "
        "FROM `" + table + "` "
        "WHERE league_id = '" + _esc(_get_active_league_id()) + "' "
        "AND LOWER(team_name) LIKE '%" + _esc(team_name.lower()) + "%' "
        "ORDER BY position, name"
    )

    logger.info("get_team_roster: team_name=%s", team_name)
    rows = bq.run_query(sql)
    logger.info("get_team_roster: returned %d players", len(rows))
    return rows


def get_league_overview() -> dict[str, Any]:
    """
    Get a full overview of the dataset: total players, total teams, list of all
    team names, position breakdown, and nationality diversity. Use this when asked
    about the league, competition, dataset, or what data is available.

    Returns
    -------
    dict
        total_players: int — number of players in the dataset
        total_teams: int — number of distinct national teams
        teams: list of str — all team names sorted alphabetically
        position_breakdown: dict — player counts keyed by position code (GK/DEF/MID/FWD)
        top_nationalities: list of dict — top 10 nationalities by player count
        competition: str — competition name and league ID
    """
    table = config.table("gold_player_stats")
    lid = _get_active_league_id()
    league_filter = "WHERE league_id = '" + _esc(lid) + "'"

    counts_sql = (
        "SELECT COUNT(*) as total_players, COUNT(DISTINCT team_name) as total_teams "
        "FROM `" + table + "` " + league_filter
    )
    counts = bq.run_query(counts_sql)
    total_players = counts[0]["total_players"] if counts else 0
    total_teams = counts[0]["total_teams"] if counts else 0

    teams_sql = (
        "SELECT DISTINCT team_name FROM `" + table + "` "
        + league_filter + " ORDER BY team_name"
    )
    teams = [r["team_name"] for r in bq.run_query(teams_sql)]

    pos_sql = (
        "SELECT position, COUNT(*) as cnt FROM `" + table + "` "
        + league_filter + " GROUP BY position ORDER BY position"
    )
    position_breakdown = {r["position"]: r["cnt"] for r in bq.run_query(pos_sql)}

    nat_sql = (
        "SELECT nationality, COUNT(*) as cnt FROM `" + table + "` "
        + league_filter + " GROUP BY nationality ORDER BY cnt DESC LIMIT 10"
    )
    top_nationalities = [
        {"nationality": r["nationality"], "count": r["cnt"]}
        for r in bq.run_query(nat_sql)
    ]

    league_name = _LEAGUE_DISPLAY_NAMES.get(int(lid), f"League {lid}")
    logger.info(
        "get_league_overview: %d players across %d teams", total_players, total_teams
    )
    return {
        "total_players": total_players,
        "total_teams": total_teams,
        "teams": teams,
        "position_breakdown": position_breakdown,
        "top_nationalities": top_nationalities,
        "competition": f"{league_name} (League {lid})",
    }


def get_top_performers(stat: str = "goals", limit: int = 10) -> list[dict[str, Any]]:
    """Get top players ranked by goals, assists, or rating.

    stat must be one of: 'goals', 'assists', 'rating'
    Use this when asked about: top scorers, most goals, best rated players,
    top assisters, leaderboard, who scored the most, best players by performance.
    Returns ranked list with player name, team, and stat value.

    Parameters
    ----------
    stat : str
        Statistic to rank by. One of 'goals', 'assists', 'rating'.
    limit : int
        Maximum number of players to return. Capped at 20.
    """
    valid = {"goals", "assists", "rating"}
    if stat not in valid:
        stat = "goals"
    safe_limit = min(max(1, int(limit)), 20)
    table = config.table("gold_top_performers")
    sql = (
        "SELECT player_name, team_name, "
        + stat
        + ", rank FROM `"
        + table
        + "` WHERE stat_type = '"
        + stat
        + "' AND "
        + stat
        + " IS NOT NULL ORDER BY rank ASC LIMIT "
        + str(safe_limit)
    )
    logger.info("get_top_performers: stat=%s limit=%d", stat, safe_limit)
    rows = bq.run_query(sql)
    if not rows:
        return [
            {
                "message": (
                    "Top performers data not yet loaded. "
                    "Ask me to refresh the scouting data."
                )
            }
        ]
    return rows


# Only leagues verified to return fixture data from free-api-live-football-data.
# Bundesliga is ID 54 on this API (not 78 as on api-football-v1).
# World Cup 2026 (77) returns 0 matches until ~June 11 — kept as a known placeholder.
_LEAGUE_MAP: dict[str, int] = {
    # World Cup
    "world cup": 77,
    "world cup 2026": 77,
    "wc2026": 77,
    "wc26": 77,
    "fifa world cup": 77,
    # WC Qualification
    "uefa wc qualification": 10195,
    "wc qualification": 10195,
    "qualification": 10195,
    # Top 5 European leagues
    "premier league": 47,
    "epl": 47,
    "la liga": 140,
    "bundesliga": 54,
    "serie a": 135,
    "serie a italy": 135,
    "ligue 1": 61,
    # European cups
    "champions league": 42,
    "ucl": 42,
    # Other verified leagues
    "mls": 253,
    "brasileirao": 71,
    "scottish premiership": 108,
    "scottish prem": 108,
}

_LEAGUE_DISPLAY_NAMES: dict[int, str] = {
    77: "World Cup 2026",
    10195: "UEFA WC Qualification",
    47: "Premier League",
    42: "Champions League",
    140: "La Liga",
    54: "Bundesliga",
    135: "Serie A",
    61: "Ligue 1",
    71: "Brasileirao",
    253: "MLS",
    108: "Scottish Premiership",
}


def switch_league(league_name: str) -> dict[str, Any]:
    """Switch the active scouting league. Call this when the user asks to change league,
    switch to a different competition, or view a different tournament.

    Available leagues include (but are not limited to):
    - "UEFA WC Qualification" → 10195 (current), "World Cup 2026" → 77
    - "Premier League" → 47, "Champions League" → 42, "La Liga" → 140
    - "Bundesliga" → 78, "Serie A" → 71, "Ligue 1" → 61
    - "AFCON" / "Africa Cup of Nations" → 6, "Copa América" → 9
    - "MLS" → 253, "Saudi Pro League" → 307, "Eredivisie" → 88
    If the league name is not in the built-in map, the system searches for it automatically.

    When called: updates the active league, triggers a data refresh for the new league,
    reruns the pipeline. Returns confirmation of the switch.
    """
    import src.utils.football_api as _fa_mod
    from src.pipeline.transform import run_all
    from src.utils.football_api import football_api

    emit_progress(f"🔍 Finding league: {league_name}", "running", 10)

    query = league_name.strip().lower()
    league_id: Optional[int] = None
    matched_name = league_name

    for key, lid in _LEAGUE_MAP.items():
        if key in query:
            league_id = lid
            matched_name = _LEAGUE_DISPLAY_NAMES.get(lid, key.title())
            break

    if league_id is None:
        logger.info("switch_league: no map match for %r — searching API", league_name)
        try:
            data = football_api._get("/football-leagues-search", {"search": league_name})
            resp = data.get("response", {})
            results: list = []
            if isinstance(resp, list):
                results = resp
            elif isinstance(resp, dict):
                results = resp.get("leagues") or resp.get("data") or resp.get("results") or []
            if results:
                first = results[0]
                raw_id = first.get("id") or first.get("leagueId") or first.get("league_id")
                if raw_id is not None:
                    league_id = int(raw_id)
                    matched_name = first.get("name") or first.get("leagueName") or league_name
        except Exception as exc:
            logger.warning("switch_league: API search failed: %s", exc)

    if league_id is None:
        emit_progress(f"❌ League not found: {league_name}", "error", 100)
        return {
            "status": "error",
            "message": (
                f"Could not find league: '{league_name}'. "
                "Try 'Premier League', 'Champions League', 'World Cup 2026', or 'UEFA WC Qualification'."
            ),
        }

    logger.info("switch_league: switching to %r (id=%d)", matched_name, league_id)
    _fa_mod._WORLD_CUP_LEAGUE_ID = league_id

    try:
        _direct_api_ingest(_emit=emit_progress, force_refresh_fixtures=True)
    except Exception as exc:
        logger.error("switch_league: data ingest failed: %s", exc)
        emit_progress("❌ Data ingest failed", "error", 100)
        return {
            "status": "error",
            "league_name": matched_name,
            "league_id": league_id,
            "message": f"Switched league ID but data refresh failed: {exc}",
        }

    emit_progress("⚙️ Running Silver transforms...", "running", 75)

    try:
        run_all()
    except Exception as exc:
        logger.error("switch_league: pipeline failed: %s", exc)
        emit_progress("❌ Pipeline failed", "error", 100)
        return {
            "status": "partial",
            "league_name": matched_name,
            "league_id": league_id,
            "message": f"League switched and data ingested, but pipeline rebuild failed: {exc}",
        }

    emit_progress("🏆 Building Gold tables...", "done", 90)
    emit_progress(f"✅ Switch complete: {matched_name}", "done", 100)

    return {
        "status": "switched",
        "league_name": matched_name,
        "league_id": league_id,
        "message": f"Switched to {matched_name}. Data refreshed with new league data.",
    }


def _direct_api_ingest(_emit=None, force_refresh_fixtures: bool = False) -> None:
    """Write fresh fixture and squad data to Bronze tables via the football API.

    Mirrors the per-team pattern used by scripts/ingest_all_players.py so each
    squad is written via write_bronze_team_squads(), which dual-writes to both
    bronze_team_squads and bronze_players with proper field mapping.

    When config.FAST_LEAGUE_SWITCH is True (default), fetches up to 20 teams
    concurrently with max_workers=5, cutting switch time from ~60 s to ~15 s.
    When False, falls back to the original sequential loop (all teams).

    _emit: optional callable(step, status, progress) for progress reporting.
    force_refresh_fixtures: bypass the Bronze cache and always fetch fresh fixtures
        from the API. Required when switching leagues so stale cached fixtures from
        the previous league are not used.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from src.ingestion.bq_loader import write_bronze_fixtures, write_bronze_team_squads
    from src.utils.football_api import football_api

    def _p(step: str, status: str, pct: int) -> None:
        if _emit is not None:
            _emit(step, status, pct)

    logger.info("Syncing latest football data directly from API...")
    _p("📡 Fetching fixtures from API...", "running", 25)
    try:
        fixtures = football_api.get_world_cup_fixtures(force_refresh=force_refresh_fixtures)
        write_bronze_fixtures(fixtures)
    except Exception as exc:
        logger.warning("Fixture fetch failed (non-fatal): %s", exc)
        fixtures = []

    teams: dict[int, str] = {}
    for match in fixtures:
        for side in ("home", "away"):
            side_data = match.get(side, {})
            if isinstance(side_data, dict) and side_data.get("id"):
                tid = int(side_data["id"])
                if tid not in teams:
                    teams[tid] = side_data.get("name", str(tid))

    logger.info("Direct API ingest: %d teams found in fixtures", len(teams))

    if config.FAST_LEAGUE_SWITCH:
        _MAX_TEAMS = 20
        team_list = list(teams.items())[:_MAX_TEAMS]
        total = len(team_list)
        _p(f"👥 Fetching squads (0/{total})...", "running", 35)
        completed = 0

        def _fetch_and_write(team_id: int, team_name: str) -> None:
            players = football_api.get_players_by_team(team_id)
            write_bronze_team_squads(team_id, players, team_name=team_name)

        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {
                executor.submit(_fetch_and_write, tid, tname): (tid, tname)
                for tid, tname in team_list
            }
            for future in as_completed(futures):
                future.result()
                completed += 1
                pct = 35 + int(25 * completed / max(total, 1))
                _p(
                    f"👥 Fetching squads ({completed}/{total})...",
                    "running",
                    pct,
                )
        logger.info(
            "Direct API ingest: fetched %d/%d teams (fast mode)", completed, len(teams)
        )
    else:
        _p("👥 Fetching player squads...", "running", 45)
        for team_id, team_name in teams.items():
            players = football_api.get_players_by_team(team_id)
            write_bronze_team_squads(team_id, players, team_name=team_name)

    # Top performers (supplementary — non-fatal if endpoint not available for this league)
    try:
        from src.ingestion.bq_loader import write_bronze_top_performers
        scorers = football_api.get_top_scorers()
        assisters = football_api.get_top_assisters()
        rated = football_api.get_top_rated()
        write_bronze_top_performers(scorers, assisters, rated)
        logger.info(
            "Direct API ingest: top performers written (%d scorers, %d assisters, %d rated)",
            len(scorers),
            len(assisters),
            len(rated),
        )
    except Exception as exc:
        logger.warning("Top performers ingestion skipped (non-fatal): %s", exc)
    _p("💾 Writing to BigQuery Bronze...", "done", 60)
    logger.info("Direct API ingest: complete")


def refresh_scouting_data() -> dict[str, Any]:
    """
    Triggers a full data refresh: syncs latest football data via Fivetran
    (preferred) or falls back to direct football API ingestion if Fivetran is
    unavailable, then reruns the Bronze→Silver→Gold pipeline. Use this when the
    user asks to update, refresh, or sync the scouting data. Returns a status
    dict with steps completed and the sync method used.
    """
    from src.ingestion.fivetran_trigger import poll_sync_status, trigger_sync
    from src.pipeline.transform import run_all

    sync_method = "fivetran"
    sync_triggered = False

    emit_progress("🔄 Triggering Fivetran sync...", "running", 15)

    try:
        logger.info("refresh_scouting_data: triggering Fivetran sync")
        trigger_sync()
        emit_progress("⏳ Waiting for sync to complete...", "running", 30)
        poll_sync_status(timeout_seconds=120)
        sync_triggered = True
        logger.info("refresh_scouting_data: Fivetran sync complete")
    except Exception as exc:
        logger.warning(
            "refresh_scouting_data: Fivetran unavailable (%s), falling back to direct API",
            exc,
        )
        sync_method = "direct_api"
        emit_progress("📡 Pulling latest data from API...", "running", 50)
        try:
            _direct_api_ingest()
            emit_progress("💾 Writing to BigQuery Bronze...", "done", 65)
            sync_triggered = True
        except Exception as api_exc:
            logger.error("refresh_scouting_data: direct API fallback failed: %s", api_exc)
            emit_progress("❌ Data sync failed", "error", 100)
            return {
                "status": "error",
                "message": "Syncing latest football data directly from API...",
                "step_failed": "sync",
                "sync_method": sync_method,
            }

    emit_progress("⚙️ Running pipeline transforms...", "running", 85)

    try:
        run_all()
        logger.info("refresh_scouting_data: pipeline complete")
    except Exception as exc:
        logger.error("refresh_scouting_data: pipeline step failed: %s", exc)
        emit_progress("❌ Pipeline failed", "error", 100)
        return {
            "status": "error",
            "message": str(exc),
            "step_failed": "pipeline",
            "sync_triggered": sync_triggered,
            "sync_method": sync_method,
        }

    emit_progress("✅ Data refresh complete", "done", 100)

    return {
        "status": "complete",
        "sync_triggered": sync_triggered,
        "sync_method": sync_method,
        "pipeline_rerun": True,
        "message": f"Data refreshed via {sync_method}",
    }
