from unittest.mock import MagicMock, patch

from src.agent.tools import (
    _direct_api_ingest,
    get_league_overview,
    get_player_detail,
    get_team_roster,
    get_top_performers,
    get_top_players_by_position,
    query_players,
    query_team_summary,
    refresh_scouting_data,
    switch_league,
)
from src.utils import config as config_module


# ---------------------------------------------------------------------------
# query_players
# ---------------------------------------------------------------------------


def test_query_players_no_filters_uses_only_league_filter():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        query_players()
        sql = mock_bq.run_query.call_args[0][0]
        # league_id filter is always applied even with no other filters
        assert "WHERE league_id = " in sql
        assert "LIMIT" in sql


def test_query_players_returns_rows_from_bq():
    with patch("src.agent.tools.bq") as mock_bq:
        expected = [{"player_id": "1", "name": "Mbappe"}]
        mock_bq.run_query.return_value = expected
        assert query_players() == expected


def test_query_players_empty_result_returns_empty_list():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        assert query_players(position="Goalkeeper") == []


def test_query_players_position_filter_in_sql():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        query_players(position="Forward")
        sql = mock_bq.run_query.call_args[0][0]
        assert "position" in sql.lower()
        assert "FWD" in sql  # _normalize_position converts "Forward" → "FWD"


def test_query_players_nationality_filter_in_sql():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        query_players(nationality="French")
        sql = mock_bq.run_query.call_args[0][0]
        assert "nationality" in sql.lower()
        assert "french" in sql.lower()


def test_query_players_team_name_filter_in_sql():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        query_players(team_name="France")
        sql = mock_bq.run_query.call_args[0][0]
        assert "team_name" in sql.lower()
        assert "france" in sql.lower()


def test_query_players_age_range_in_sql():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        query_players(min_age=20, max_age=25)
        sql = mock_bq.run_query.call_args[0][0]
        assert "age >= 20" in sql
        assert "age <= 25" in sql


def test_query_players_multiple_filters_combined():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        query_players(position="Midfielder", nationality="Spanish", min_age=22)
        sql = mock_bq.run_query.call_args[0][0]
        assert "position" in sql.lower()
        assert "nationality" in sql.lower()
        assert "age >= 22" in sql


def test_query_players_uses_config_table(monkeypatch):
    monkeypatch.setattr(config_module.config, "PROJECT_ID", "proj-test")
    monkeypatch.setattr(config_module.config, "BQ_DATASET", "ds_test")
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        query_players()
        sql = mock_bq.run_query.call_args[0][0]
        assert "proj-test.ds_test.gold_player_stats" in sql


def test_query_players_no_hardcoded_table_string():
    """SQL must reference the table via config, not a hardcoded string."""
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        with patch.object(config_module.config, "table", wraps=config_module.config.table) as mock_table:
            query_players()
            mock_table.assert_called_with("gold_player_stats")


# ---------------------------------------------------------------------------
# query_team_summary
# ---------------------------------------------------------------------------


def test_query_team_summary_by_name_returns_first_row():
    with patch("src.agent.tools.bq") as mock_bq:
        expected = {"team_id": "5", "team_name": "France", "wins": 3}
        mock_bq.run_query.return_value = [expected]
        assert query_team_summary(team_name="France") == expected


def test_query_team_summary_empty_returns_empty_dict():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        assert query_team_summary(team_name="Atlantis FC") == {}


def test_query_team_summary_team_name_in_sql():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        query_team_summary(team_name="France")
        sql = mock_bq.run_query.call_args[0][0]
        assert "team_name" in sql.lower()
        assert "france" in sql.lower()


def test_query_team_summary_team_id_in_sql():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        query_team_summary(team_id="42")
        sql = mock_bq.run_query.call_args[0][0]
        assert "team_id" in sql
        assert "'42'" in sql


def test_query_team_summary_uses_config_table(monkeypatch):
    monkeypatch.setattr(config_module.config, "PROJECT_ID", "proj-test")
    monkeypatch.setattr(config_module.config, "BQ_DATASET", "ds_test")
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        query_team_summary(team_name="France")
        sql = mock_bq.run_query.call_args[0][0]
        assert "proj-test.ds_test.gold_team_summary" in sql


def test_query_team_summary_no_args_returns_all_teams():
    with patch("src.agent.tools.bq") as mock_bq:
        expected = [{"team_id": "1", "team_name": "France", "points": 9}]
        mock_bq.run_query.return_value = expected
        result = query_team_summary()
        assert isinstance(result, list)
        assert result == expected
        sql = mock_bq.run_query.call_args[0][0]
        assert "ORDER BY points DESC" in sql
        # league_id filter is always applied
        assert "WHERE league_id = " in sql


# ---------------------------------------------------------------------------
# get_player_detail
# ---------------------------------------------------------------------------


def test_get_player_detail_by_name_returns_first_row():
    with patch("src.agent.tools.bq") as mock_bq:
        expected = {"player_id": "1", "name": "Kylian Mbappe"}
        mock_bq.run_query.return_value = [expected]
        assert get_player_detail(player_name="Mbappe") == expected


def test_get_player_detail_not_found_returns_empty_dict():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        assert get_player_detail(player_name="Ghost Player") == {}


def test_get_player_detail_no_args_skips_query():
    with patch("src.agent.tools.bq") as mock_bq:
        result = get_player_detail()
        assert result == {}
        mock_bq.run_query.assert_not_called()


def test_get_player_detail_name_in_sql():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        get_player_detail(player_name="Mbappe")
        sql = mock_bq.run_query.call_args[0][0]
        assert "name" in sql.lower()
        assert "mbappe" in sql.lower()


def test_get_player_detail_id_in_sql():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        get_player_detail(player_id="99")
        sql = mock_bq.run_query.call_args[0][0]
        assert "player_id" in sql
        assert "'99'" in sql


def test_get_player_detail_uses_config_table(monkeypatch):
    monkeypatch.setattr(config_module.config, "PROJECT_ID", "proj-test")
    monkeypatch.setattr(config_module.config, "BQ_DATASET", "ds_test")
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        get_player_detail(player_name="Mbappe")
        sql = mock_bq.run_query.call_args[0][0]
        assert "proj-test.ds_test.gold_player_stats" in sql


# ---------------------------------------------------------------------------
# get_top_players_by_position
# ---------------------------------------------------------------------------


def test_get_top_players_by_position_sql_has_order_by_age_asc():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        get_top_players_by_position("Midfielder")
        sql = mock_bq.run_query.call_args[0][0]
        # Ranks by active league first then age ASC so cross-league fallback
        # works while preserving the youngest-first ordering.
        assert "age ASC" in sql
        assert "ORDER BY" in sql


def test_get_top_players_by_position_applies_position_filter():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        get_top_players_by_position("Defender")
        sql = mock_bq.run_query.call_args[0][0]
        assert "DEF" in sql  # _normalize_position converts "Defender" → "DEF"


def test_get_top_players_by_position_custom_limit_in_sql():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        get_top_players_by_position("Forward", limit=5)
        sql = mock_bq.run_query.call_args[0][0]
        assert "LIMIT 5" in sql


def test_get_top_players_by_position_default_limit_in_sql():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        get_top_players_by_position("Goalkeeper")
        sql = mock_bq.run_query.call_args[0][0]
        assert "LIMIT 10" in sql


def test_get_top_players_by_position_empty_returns_empty_list():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        assert get_top_players_by_position("Goalkeeper") == []


def test_get_top_players_by_position_uses_config_table(monkeypatch):
    monkeypatch.setattr(config_module.config, "PROJECT_ID", "proj-test")
    monkeypatch.setattr(config_module.config, "BQ_DATASET", "ds_test")
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        get_top_players_by_position("Forward")
        sql = mock_bq.run_query.call_args[0][0]
        assert "proj-test.ds_test.gold_player_stats" in sql


# ---------------------------------------------------------------------------
# refresh_scouting_data
# ---------------------------------------------------------------------------

_FIVETRAN_TRIGGER = "src.ingestion.fivetran_trigger"
_PIPELINE_TRANSFORM = "src.pipeline.transform"
_TOOLS_MODULE = "src.agent.tools"


def test_refresh_scouting_data_fivetran_happy_path():
    with (
        patch(f"{_FIVETRAN_TRIGGER}.trigger_sync") as mock_trigger,
        patch(f"{_FIVETRAN_TRIGGER}.poll_sync_status") as mock_poll,
        patch(f"{_PIPELINE_TRANSFORM}.run_all") as mock_run,
    ):
        result = refresh_scouting_data()
    mock_trigger.assert_called_once()
    mock_poll.assert_called_once_with(timeout_seconds=120)
    mock_run.assert_called_once()
    assert result == {
        "status": "complete",
        "sync_triggered": True,
        "sync_method": "fivetran",
        "pipeline_rerun": True,
        "message": "Data refreshed via fivetran",
    }


def test_refresh_scouting_data_fivetran_fails_falls_back_to_direct_api():
    """When Fivetran raises any exception, the direct API path is used instead."""
    with (
        patch(f"{_FIVETRAN_TRIGGER}.trigger_sync", side_effect=RuntimeError("HTTP 404")),
        patch(f"{_FIVETRAN_TRIGGER}.poll_sync_status"),
        patch(f"{_TOOLS_MODULE}._direct_api_ingest") as mock_direct,
        patch(f"{_PIPELINE_TRANSFORM}.run_all") as mock_run,
    ):
        result = refresh_scouting_data()
    mock_direct.assert_called_once()
    mock_run.assert_called_once()
    assert result == {
        "status": "complete",
        "sync_triggered": True,
        "sync_method": "direct_api",
        "pipeline_rerun": True,
        "message": "Data refreshed via direct_api",
    }


def test_refresh_scouting_data_fivetran_and_direct_api_both_fail():
    """When both Fivetran and the direct API fallback fail, return a user-friendly error."""
    with (
        patch(f"{_FIVETRAN_TRIGGER}.trigger_sync", side_effect=RuntimeError("connection refused")),
        patch(f"{_FIVETRAN_TRIGGER}.poll_sync_status"),
        patch(f"{_TOOLS_MODULE}._direct_api_ingest", side_effect=RuntimeError("API down")),
        patch(f"{_PIPELINE_TRANSFORM}.run_all") as mock_run,
    ):
        result = refresh_scouting_data()
    mock_run.assert_not_called()
    assert result["status"] == "error"
    assert result["step_failed"] == "sync"
    assert result["sync_method"] == "direct_api"
    # Message must be user-friendly, not exposing internal error strings
    assert "Syncing latest football data directly from API" in result["message"]
    assert "API down" not in result["message"]
    assert "connection refused" not in result["message"]


def test_refresh_scouting_data_pipeline_failure_returns_error():
    with (
        patch(f"{_FIVETRAN_TRIGGER}.trigger_sync"),
        patch(f"{_FIVETRAN_TRIGGER}.poll_sync_status"),
        patch(f"{_PIPELINE_TRANSFORM}.run_all", side_effect=RuntimeError("pipeline boom")),
    ):
        result = refresh_scouting_data()
    assert result["status"] == "error"
    assert result["step_failed"] == "pipeline"
    assert result["sync_method"] == "fivetran"
    assert "pipeline boom" in result["message"]


def test_refresh_scouting_data_fallback_pipeline_failure():
    """Pipeline failure after direct API fallback includes sync_method in the error."""
    with (
        patch(f"{_FIVETRAN_TRIGGER}.trigger_sync", side_effect=RuntimeError("no connector")),
        patch(f"{_FIVETRAN_TRIGGER}.poll_sync_status"),
        patch(f"{_TOOLS_MODULE}._direct_api_ingest"),
        patch(f"{_PIPELINE_TRANSFORM}.run_all", side_effect=RuntimeError("bq error")),
    ):
        result = refresh_scouting_data()
    assert result["status"] == "error"
    assert result["step_failed"] == "pipeline"
    assert result["sync_method"] == "direct_api"
    assert result["sync_triggered"] is True


# ---------------------------------------------------------------------------
# _direct_api_ingest
# ---------------------------------------------------------------------------


def test_direct_api_ingest_writes_fixtures_and_squads():
    """_direct_api_ingest fetches fixtures, extracts teams, and writes squads per team."""
    fake_fixtures = [
        {"home": {"id": 1, "name": "France"}, "away": {"id": 2, "name": "Germany"}},
        {"home": {"id": 3, "name": "Spain"}, "away": {"id": 1, "name": "France"}},
    ]
    mock_fa = MagicMock()
    mock_fa.get_world_cup_fixtures.return_value = fake_fixtures
    mock_fa.get_players_by_team.return_value = [{"id": 99, "name": "Player A"}]

    with (
        patch("src.ingestion.bq_loader.write_bronze_fixtures") as mock_write_fix,
        patch("src.ingestion.bq_loader.write_bronze_team_squads") as mock_write_sq,
        patch("src.utils.football_api.football_api", mock_fa),
    ):
        _direct_api_ingest()

    mock_write_fix.assert_called_once_with(fake_fixtures)
    # Three unique teams: 1, 2, 3
    assert mock_fa.get_players_by_team.call_count == 3
    assert mock_write_sq.call_count == 3


def test_direct_api_ingest_deduplicates_teams():
    """Each team ID appears only once even when it shows up in multiple fixtures."""
    fake_fixtures = [
        {"home": {"id": 10, "name": "Italy"}, "away": {"id": 10, "name": "Italy"}},
        {"home": {"id": 10, "name": "Italy"}, "away": {"id": 20, "name": "Brazil"}},
    ]
    mock_fa = MagicMock()
    mock_fa.get_world_cup_fixtures.return_value = fake_fixtures
    mock_fa.get_players_by_team.return_value = []

    with (
        patch("src.ingestion.bq_loader.write_bronze_fixtures"),
        patch("src.ingestion.bq_loader.write_bronze_team_squads"),
        patch("src.utils.football_api.football_api", mock_fa),
    ):
        _direct_api_ingest()

    assert mock_fa.get_players_by_team.call_count == 2


def test_direct_api_ingest_skips_non_dict_sides():
    """Fixtures with missing or non-dict home/away entries don't crash the ingest."""
    fake_fixtures = [
        {"home": None, "away": {"id": 5, "name": "Portugal"}},
        {"home": {"id": 6, "name": "Croatia"}, "away": None},
        {},
    ]
    mock_fa = MagicMock()
    mock_fa.get_world_cup_fixtures.return_value = fake_fixtures
    mock_fa.get_players_by_team.return_value = []

    with (
        patch("src.ingestion.bq_loader.write_bronze_fixtures"),
        patch("src.ingestion.bq_loader.write_bronze_team_squads"),
        patch("src.utils.football_api.football_api", mock_fa),
    ):
        _direct_api_ingest()

    assert mock_fa.get_players_by_team.call_count == 2


# ---------------------------------------------------------------------------
# get_team_roster
# ---------------------------------------------------------------------------


def test_get_team_roster_filters_by_team_name():
    with patch("src.agent.tools.bq") as mock_bq:
        expected = [{"name": "Mbappe", "position": "FWD", "age": 25, "nationality": "France"}]
        mock_bq.run_query.return_value = expected
        result = get_team_roster("France")
        sql = mock_bq.run_query.call_args[0][0]
        assert "team_name" in sql.lower()
        assert "france" in sql.lower()
        assert result == expected


def test_get_team_roster_sql_has_order_by():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        get_team_roster("Germany")
        sql = mock_bq.run_query.call_args[0][0]
        assert "ORDER BY" in sql


def test_get_team_roster_empty_team_returns_empty_list():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        assert get_team_roster("Atlantis") == []


def test_get_team_roster_uses_config_table(monkeypatch):
    monkeypatch.setattr(config_module.config, "PROJECT_ID", "proj-test")
    monkeypatch.setattr(config_module.config, "BQ_DATASET", "ds_test")
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        get_team_roster("France")
        sql = mock_bq.run_query.call_args[0][0]
        assert "proj-test.ds_test.gold_player_stats" in sql


# ---------------------------------------------------------------------------
# get_league_overview
# ---------------------------------------------------------------------------


def _make_bq_side_effect():
    def side_effect(sql):
        if "COUNT(DISTINCT" in sql:
            return [{"total_players": 1391, "total_teams": 50}]
        if "DISTINCT team_name" in sql:
            return [{"team_name": "France"}, {"team_name": "Germany"}]
        if "GROUP BY position" in sql:
            return [
                {"position": "GK", "cnt": 100},
                {"position": "DEF", "cnt": 400},
                {"position": "MID", "cnt": 500},
                {"position": "FWD", "cnt": 391},
            ]
        if "GROUP BY nationality" in sql:
            return [{"nationality": "French", "cnt": 30}, {"nationality": "German", "cnt": 28}]
        return []

    return side_effect


def test_get_league_overview_returns_required_keys():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.side_effect = _make_bq_side_effect()
        result = get_league_overview()
    for key in ("total_players", "total_teams", "teams", "position_breakdown", "top_nationalities", "competition"):
        assert key in result


def test_get_league_overview_totals_from_counts_query():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.side_effect = _make_bq_side_effect()
        result = get_league_overview()
    assert result["total_players"] == 1391
    assert result["total_teams"] == 50


def test_get_league_overview_teams_sorted_alphabetically():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.side_effect = _make_bq_side_effect()
        result = get_league_overview()
    assert result["teams"] == ["France", "Germany"]


def test_get_league_overview_position_breakdown_is_dict():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.side_effect = _make_bq_side_effect()
        result = get_league_overview()
    assert isinstance(result["position_breakdown"], dict)
    assert result["position_breakdown"]["GK"] == 100


def test_get_league_overview_competition_string():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.side_effect = _make_bq_side_effect()
        result = get_league_overview()
    assert "10195" in result["competition"]


# ---------------------------------------------------------------------------
# switch_league
# ---------------------------------------------------------------------------

_TOOLS_MODULE = "src.agent.tools"
_PIPELINE_TRANSFORM = "src.pipeline.transform"


def test_switch_league_known_name_maps_to_correct_id():
    """Exact key in LEAGUE_MAP resolves to the right league_id without API call."""
    mock_fa = MagicMock()
    with (
        patch("src.utils.football_api.football_api", mock_fa),
        patch(f"{_TOOLS_MODULE}._direct_api_ingest"),
        patch(f"{_PIPELINE_TRANSFORM}.run_all"),
    ):
        result = switch_league("premier league")
    assert result["status"] == "switched"
    assert result["league_id"] == 47
    assert result["league_name"] == "Premier League"
    mock_fa._get.assert_not_called()


def test_switch_league_fuzzy_match_world_cup():
    """Partial name 'world cup' fuzzy-matches to league_id 77."""
    mock_fa = MagicMock()
    with (
        patch("src.utils.football_api.football_api", mock_fa),
        patch(f"{_TOOLS_MODULE}._direct_api_ingest"),
        patch(f"{_PIPELINE_TRANSFORM}.run_all"),
    ):
        result = switch_league("world cup")
    assert result["status"] == "switched"
    assert result["league_id"] == 77
    assert result["league_name"] == "World Cup 2026"
    mock_fa._get.assert_not_called()


def test_switch_league_fuzzy_match_phrase_in_sentence():
    """Input containing 'champions league' anywhere still maps to league_id 42."""
    mock_fa = MagicMock()
    with (
        patch("src.utils.football_api.football_api", mock_fa),
        patch(f"{_TOOLS_MODULE}._direct_api_ingest"),
        patch(f"{_PIPELINE_TRANSFORM}.run_all"),
    ):
        result = switch_league("switch to the champions league please")
    assert result["status"] == "switched"
    assert result["league_id"] == 42


def test_switch_league_unknown_name_falls_back_to_api_search():
    """Unknown league name triggers football API search and uses the first result."""
    mock_fa = MagicMock()
    mock_fa._get.return_value = {
        "response": [{"id": 999, "name": "Fictional Super League"}]
    }
    with (
        patch("src.utils.football_api.football_api", mock_fa),
        patch(f"{_TOOLS_MODULE}._direct_api_ingest"),
        patch(f"{_PIPELINE_TRANSFORM}.run_all"),
    ):
        result = switch_league("fictional super league xyz")
    assert result["status"] == "switched"
    assert result["league_id"] == 999
    assert result["league_name"] == "Fictional Super League"
    mock_fa._get.assert_called_once()


def test_switch_league_api_search_empty_returns_error():
    """If API search returns nothing, switch_league returns an error dict."""
    mock_fa = MagicMock()
    mock_fa._get.return_value = {"response": []}
    with (
        patch("src.utils.football_api.football_api", mock_fa),
        patch(f"{_TOOLS_MODULE}._direct_api_ingest") as mock_ingest,
        patch(f"{_PIPELINE_TRANSFORM}.run_all") as mock_run,
    ):
        result = switch_league("nonexistent league zzzz")
    assert result["status"] == "error"
    assert "nonexistent league zzzz" in result["message"]
    mock_ingest.assert_not_called()
    mock_run.assert_not_called()


def test_switch_league_ingest_failure_returns_error():
    """If _direct_api_ingest raises, switch_league returns error with league info."""
    mock_fa = MagicMock()
    with (
        patch("src.utils.football_api.football_api", mock_fa),
        patch(f"{_TOOLS_MODULE}._direct_api_ingest", side_effect=RuntimeError("API down")),
        patch(f"{_PIPELINE_TRANSFORM}.run_all") as mock_run,
    ):
        result = switch_league("premier league")
    assert result["status"] == "error"
    assert result["league_id"] == 47
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# get_top_performers
# ---------------------------------------------------------------------------


def test_get_top_performers_returns_rows_from_bq():
    with patch("src.agent.tools.bq") as mock_bq:
        expected = [{"player_name": "Ronaldo", "team_name": "Portugal", "goals": 12, "rank": 1}]
        mock_bq.run_query.return_value = expected
        result = get_top_performers(stat="goals", limit=10)
    assert result == expected


def test_get_top_performers_sql_filters_by_stat_type():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        get_top_performers(stat="assists", limit=5)
        sql = mock_bq.run_query.call_args[0][0]
        assert "stat_type = 'assists'" in sql
        assert "assists IS NOT NULL" in sql
        assert "LIMIT 5" in sql


def test_get_top_performers_invalid_stat_defaults_to_goals():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        get_top_performers(stat="nonsense")
        sql = mock_bq.run_query.call_args[0][0]
        assert "stat_type = 'goals'" in sql


def test_get_top_performers_limit_capped_at_20():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        get_top_performers(stat="rating", limit=999)
        sql = mock_bq.run_query.call_args[0][0]
        assert "LIMIT 20" in sql


def test_get_top_performers_empty_bq_returns_message():
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        result = get_top_performers(stat="goals")
    assert isinstance(result, list)
    assert len(result) == 1
    assert "message" in result[0]
    assert "refresh" in result[0]["message"].lower()


def test_get_top_performers_uses_gold_top_performers_table(monkeypatch):
    monkeypatch.setattr(config_module.config, "PROJECT_ID", "proj-test")
    monkeypatch.setattr(config_module.config, "BQ_DATASET", "ds_test")
    with patch("src.agent.tools.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        get_top_performers(stat="goals")
        sql = mock_bq.run_query.call_args[0][0]
        assert "proj-test.ds_test.gold_top_performers" in sql


def test_switch_league_pipeline_failure_returns_partial():
    """If run_all raises after successful ingest, returns partial status."""
    mock_fa = MagicMock()
    with (
        patch("src.utils.football_api.football_api", mock_fa),
        patch(f"{_TOOLS_MODULE}._direct_api_ingest"),
        patch(f"{_PIPELINE_TRANSFORM}.run_all", side_effect=RuntimeError("BQ error")),
    ):
        result = switch_league("bundesliga")
    assert result["status"] == "partial"
    assert result["league_id"] == 54
    assert "BQ error" in result["message"]
