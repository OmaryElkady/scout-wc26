from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

_SAMPLE_REPORT = {
    "player_name": "Kylian Mbappe",
    "position": "FWD",
    "team": "France",
    "nationality": "French",
    "age": 25,
    "summary": "World-class striker with exceptional pace and finishing.",
    "strengths": ["Pace", "Finishing", "Dribbling"],
    "recommendation": "Priority Target",
}

_SAMPLE_TEAMS = [
    {"team_id": "3378", "team_name": "France", "wins": 8, "draws": 2, "losses": 0},
    {"team_id": "2560", "team_name": "Brazil", "wins": 7, "draws": 3, "losses": 0},
]

_SAMPLE_PLAYERS = [
    {
        "player_id": "1",
        "name": "Kylian Mbappe",
        "position": "FWD",
        "team_name": "France",
        "nationality": "French",
        "age": 25,
    }
]


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_200():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_response_contains_required_keys():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    data = response.json()
    assert data["status"] == "ok"
    assert "model" in data
    assert "dataset" in data


# ---------------------------------------------------------------------------
# POST /query
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.agent.scout_agent.run_query", return_value="Mbappe is the top scorer.")
async def test_query_returns_200(mock_run_query):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/query", json={"question": "Who scores the most?"})
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("src.agent.scout_agent.run_query", return_value="Mbappe is the top scorer.")
async def test_query_response_shape(mock_run_query):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/query", json={"question": "Who scores the most?"})
    data = response.json()
    assert data["answer"] == "Mbappe is the top scorer."
    assert data["question"] == "Who scores the most?"


@pytest.mark.asyncio
@patch("src.agent.scout_agent.run_query", return_value="Answer.")
async def test_query_calls_run_query_with_the_question(mock_run_query):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/query", json={"question": "Find young midfielders"})
    mock_run_query.assert_called_once_with("Find young midfielders")


# ---------------------------------------------------------------------------
# POST /report/{player_name}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.agent.scout_agent.generate_scouting_report", return_value=_SAMPLE_REPORT)
async def test_report_returns_200(mock_report):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/report/Mbappe")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("src.agent.scout_agent.generate_scouting_report", return_value=_SAMPLE_REPORT)
async def test_report_response_shape(mock_report):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/report/Mbappe")
    data = response.json()
    assert data["player_name"] == "Kylian Mbappe"
    assert data["recommendation"] == "Priority Target"
    assert isinstance(data["strengths"], list)
    assert len(data["strengths"]) > 0


@pytest.mark.asyncio
@patch("src.agent.scout_agent.generate_scouting_report", return_value={})
async def test_report_returns_404_for_unknown_player(mock_report):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/report/UnknownPlayerXYZ")
    assert response.status_code == 404


@pytest.mark.asyncio
@patch("src.agent.scout_agent.generate_scouting_report", return_value=_SAMPLE_REPORT)
async def test_report_calls_generate_with_player_name(mock_report):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post("/report/Mbappe")
    mock_report.assert_called_once_with("Mbappe")


# ---------------------------------------------------------------------------
# GET /teams
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_SAMPLE_TEAMS)
async def test_teams_returns_200(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/teams")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_SAMPLE_TEAMS)
async def test_teams_response_shape(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/teams")
    data = response.json()
    assert "teams" in data
    assert isinstance(data["teams"], list)
    assert len(data["teams"]) == 2


# ---------------------------------------------------------------------------
# GET /players
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.agent.tools.query_players", return_value=_SAMPLE_PLAYERS)
async def test_players_returns_200(mock_qp):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/players")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("src.agent.tools.query_players", return_value=_SAMPLE_PLAYERS)
async def test_players_response_shape(mock_qp):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/players")
    data = response.json()
    assert "players" in data
    assert "count" in data
    assert data["count"] == len(data["players"])


@pytest.mark.asyncio
@patch("src.agent.tools.query_players", return_value=_SAMPLE_PLAYERS)
async def test_players_passes_filters_to_tool(mock_qp):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/players?position=FWD&nationality=French")
    mock_qp.assert_called_once_with(position="FWD", team_name=None, nationality="French")


@pytest.mark.asyncio
@patch("src.agent.tools.query_players", return_value=_SAMPLE_PLAYERS)
async def test_players_no_filters_passes_none(mock_qp):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/players")
    mock_qp.assert_called_once_with(position=None, team_name=None, nationality=None)


# ---------------------------------------------------------------------------
# GET /leaderboard
# ---------------------------------------------------------------------------

_SAMPLE_SCORERS = [
    {"player_name": "Ronaldo", "team_name": "Portugal", "goals": 12, "rank": 1},
    {"player_name": "Mbappe",  "team_name": "France",   "goals": 10, "rank": 2},
]


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_SAMPLE_SCORERS)
async def test_leaderboard_returns_200(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/leaderboard?stat=goals&limit=10")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_SAMPLE_SCORERS)
async def test_leaderboard_response_shape(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/leaderboard?stat=goals&limit=10")
    data = response.json()
    assert "players" in data
    assert "stat" in data
    assert "league" in data
    assert isinstance(data["players"], list)
    assert data["stat"] == "goals"


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_SAMPLE_SCORERS)
async def test_leaderboard_players_match_bq_result(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/leaderboard?stat=goals&limit=10")
    data = response.json()
    assert len(data["players"]) == 2
    assert data["players"][0]["player_name"] == "Ronaldo"


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=[])
async def test_leaderboard_empty_returns_empty_players_list(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/leaderboard?stat=assists")
    data = response.json()
    assert data["players"] == []
    assert data["stat"] == "assists"


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=[])
async def test_leaderboard_invalid_stat_defaults_to_goals(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/leaderboard?stat=invalid")
    assert response.status_code == 200
    data = response.json()
    assert data["stat"] == "goals"


# ---------------------------------------------------------------------------
# GET /progress/current
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_progress_current_returns_200():
    from src.utils.progress import reset_progress

    reset_progress()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/progress/current")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_progress_current_empty_state():
    from src.utils.progress import reset_progress

    reset_progress()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/progress/current")
    data = response.json()
    assert data["steps"] == []
    assert data["complete"] is False
    assert data["error"] is None


@pytest.mark.asyncio
async def test_progress_current_reflects_emitted_steps():
    from src.utils.progress import emit_progress, reset_progress

    reset_progress()
    emit_progress("Step 1", "running", 30)
    emit_progress("Step 2", "done", 100)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/progress/current")
    data = response.json()
    assert len(data["steps"]) == 2
    assert data["complete"] is True
    assert data["error"] is None


@pytest.mark.asyncio
async def test_progress_current_error_step_sets_error_field():
    from src.utils.progress import emit_progress, reset_progress

    reset_progress()
    emit_progress("Exploded", "error", 100)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/progress/current")
    data = response.json()
    assert data["complete"] is True
    assert data["error"] == "Exploded"


# ---------------------------------------------------------------------------
# POST /admin/switch-league  (background task — returns immediately)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.agent.tools.switch_league", return_value={"status": "switched"})
async def test_switch_league_returns_200(mock_sw):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/admin/switch-league",
            json={"league_id": 47, "league_name": "Premier League"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("src.agent.tools.switch_league", return_value={"status": "switched"})
async def test_switch_league_returns_started_status(mock_sw):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/admin/switch-league",
            json={"league_id": 47, "league_name": "Premier League"},
        )
    data = response.json()
    assert data["status"] == "started"
    assert "message" in data


@pytest.mark.asyncio
@patch("src.agent.tools.switch_league", return_value={"status": "switched"})
async def test_switch_league_resets_progress(mock_sw):
    """Route must reset progress before scheduling the task so old steps don't bleed through."""
    from src.utils.progress import emit_progress, get_current_progress, reset_progress

    reset_progress()
    emit_progress("Old stale step", "done", 100)  # leftover from previous op

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/admin/switch-league",
            json={"league_id": 47, "league_name": "Premier League"},
        )
    # After the route + background task run, progress should reflect the new operation,
    # not the stale "Old stale step".
    state = get_current_progress()
    for step in state["steps"]:
        assert step["step"] != "Old stale step", "Stale progress step leaked through after reset"


# ---------------------------------------------------------------------------
# POST /refresh  (background task — returns immediately)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.agent.tools.refresh_scouting_data", return_value={"status": "complete"})
async def test_refresh_returns_200(mock_ref):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/refresh")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("src.agent.tools.refresh_scouting_data", return_value={"status": "complete"})
async def test_refresh_returns_started_status(mock_ref):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/refresh")
    data = response.json()
    assert data["status"] == "started"
    assert "message" in data


# ---------------------------------------------------------------------------
# GET /state — loaded_leagues field
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_state_includes_loaded_leagues_field():
    """GET /state should expose which leagues already have data so the frontend
    can render a 'loaded' indicator next to each dropdown option."""
    with patch("src.api.main.bq") as mock_bq:
        mock_bq.run_query.return_value = [{"league_id": "47"}, {"league_id": "140"}]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/state")
    assert response.status_code == 200
    data = response.json()
    assert "loaded_leagues" in data
    assert 47 in data["loaded_leagues"]
    assert 140 in data["loaded_leagues"]
    # Each league in available_leagues should also have a `loaded` flag.
    for lg in data["available_leagues"]:
        assert "loaded" in lg
    pl = next(lg for lg in data["available_leagues"] if lg["id"] == 47)
    assert pl["loaded"] is True


@pytest.mark.asyncio
async def test_state_loaded_leagues_empty_when_bq_fails():
    """BQ outage must not 500 the state endpoint — _loaded_league_ids should
    catch and return an empty set."""
    with patch("src.api.main.bq") as mock_bq:
        mock_bq.run_query.side_effect = Exception("boom")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/state")
    assert response.status_code == 200
    data = response.json()
    assert data["loaded_leagues"] == []
    for lg in data["available_leagues"]:
        assert lg["loaded"] is False


# ---------------------------------------------------------------------------
# POST /admin/switch-league — fast path when data already loaded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_switch_league_fast_path_skips_ingest_when_loaded():
    """When the requested league already has player data in BigQuery, the
    switch should skip the 60s ingest and return ingested=False immediately.

    The autouse _restore_active_league_state fixture restores the module
    globals so this test's mutations don't leak into other tests.
    """
    with patch("src.api.main._loaded_league_ids", return_value={47, 140}), \
         patch("src.agent.tools.switch_league") as mock_sw:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/admin/switch-league",
                json={"league_id": 47, "league_name": "Premier League"},
            )
    assert response.status_code == 200
    data = response.json()
    assert data["ingested"] is False
    mock_sw.assert_not_called()  # ingest thread was never started


@pytest.mark.asyncio
@patch("src.agent.tools.switch_league", return_value={"status": "switched"})
async def test_switch_league_slow_path_triggers_ingest_when_not_loaded(mock_sw):
    """When the requested league has no data, the switch should trigger the
    background ingest thread and return ingested=True."""
    with patch("src.api.main._loaded_league_ids", return_value={47}):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/admin/switch-league",
                json={"league_id": 140, "league_name": "La Liga"},
            )
    assert response.status_code == 200
    data = response.json()
    assert data["ingested"] is True


# ---------------------------------------------------------------------------
# GET /teams/{name}/detail — drill-down endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_team_detail_returns_200_with_squad():
    sample_squad = [
        {"name": "GK1", "position": "GK",  "age": 28, "jersey_number": 1,  "nationality": "France", "team_name": "France", "league_id": "10195"},
        {"name": "DF1", "position": "DEF", "age": 25, "jersey_number": 4,  "nationality": "France", "team_name": "France", "league_id": "10195"},
        {"name": "DF2", "position": "DEF", "age": 27, "jersey_number": 5,  "nationality": "France", "team_name": "France", "league_id": "10195"},
        {"name": "MD1", "position": "MID", "age": 24, "jersey_number": 8,  "nationality": "France", "team_name": "France", "league_id": "10195"},
        {"name": "FW1", "position": "FWD", "age": 23, "jersey_number": 10, "nationality": "France", "team_name": "France", "league_id": "10195"},
    ]
    sample_summary = [{
        "team_name": "France", "matches_played": 10, "wins": 8, "draws": 1, "losses": 1,
        "goals_for": 22, "goals_against": 6, "goal_difference": 16, "points": 25, "league_id": "10195",
    }]
    with patch("src.api.main.bq") as mock_bq:
        # Two run_query calls — first is the squad query, second is the summary
        mock_bq.run_query.side_effect = [sample_squad, sample_summary]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/teams/France/detail")
    assert response.status_code == 200
    data = response.json()
    assert data["team_name"] == "France"
    assert len(data["squad"]) == 5
    assert data["total_players"] == 5
    # 2 DEF + 1 MID + 1 FWD → 1-2-1-1 formation
    assert data["formation"] == "1-2-1-1"
    # Position counts present
    assert data["position_counts"]["DEF"] == 2


@pytest.mark.asyncio
async def test_team_detail_empty_squad_returns_dash_formation():
    """A team with no players should return a '—' formation, not an error."""
    with patch("src.api.main.bq") as mock_bq:
        mock_bq.run_query.side_effect = [[], []]
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/teams/Atlantis/detail")
    assert response.status_code == 200
    data = response.json()
    assert data["formation"] == "—"
    assert data["total_players"] == 0
    assert data["squad"] == []


@pytest.mark.asyncio
async def test_team_detail_squad_query_failure_returns_empty_list():
    """BQ error must not bubble — return an empty squad so the modal still opens."""
    with patch("src.api.main.bq") as mock_bq:
        mock_bq.run_query.side_effect = Exception("boom")
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/teams/France/detail")
    assert response.status_code == 200
    data = response.json()
    assert data["squad"] == []


# ---------------------------------------------------------------------------
# GET /leaderboard — limit cap raised + all_leagues passthrough
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_leaderboard_accepts_limit_up_to_50():
    """Limit cap was raised from 20 to 50 so users can show top 20+ players."""
    with patch("src.api.main.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/leaderboard?stat=goals&limit=30")
    assert response.status_code == 200
    sql = mock_bq.run_query.call_args[0][0]
    assert "LIMIT 30" in sql


@pytest.mark.asyncio
async def test_leaderboard_all_leagues_param_passes_through():
    """all_leagues=true should be echoed in the response — used by the
    'All Leagues' toggle in the UI."""
    with patch("src.api.main.bq") as mock_bq:
        mock_bq.run_query.return_value = []
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/leaderboard?stat=goals&all_leagues=true")
    assert response.status_code == 200
    data = response.json()
    assert data["all_leagues"] is True


# ---------------------------------------------------------------------------
# Report player name extraction (Fix 2)
# ---------------------------------------------------------------------------


def test_extract_player_name_handles_lowercase_messi():
    """Regression: 'generate messi's report' was returning '' before fix."""
    from src.api.main import _extract_player_name_from_report_q
    assert _extract_player_name_from_report_q("generate messi's report") == "messi"


def test_extract_player_name_handles_no_possessive():
    """'messi report' with no possessive should still extract the name."""
    from src.api.main import _extract_player_name_from_report_q
    assert _extract_player_name_from_report_q("messi report") == "messi"
    assert _extract_player_name_from_report_q("download mbappe scouting report") == "mbappe"


def test_extract_player_name_handles_for_about():
    from src.api.main import _extract_player_name_from_report_q
    assert _extract_player_name_from_report_q("generate report for messi") == "messi"
    assert _extract_player_name_from_report_q(
        "create a scouting report about Bellingham"
    ) == "Bellingham"
