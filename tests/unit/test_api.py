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
