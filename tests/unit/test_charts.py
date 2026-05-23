from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app

_SQUAD_AGE_ROWS = [
    {"team_name": "Norway", "avg_age": 22.3},
    {"team_name": "England", "avg_age": 23.1},
    {"team_name": "France", "avg_age": 24.5},
]

_TEAM_ROWS = [
    {"team_name": "France", "points": 30},
    {"team_name": "Brazil", "points": 28},
    {"team_name": "Germany", "points": 25},
]

_DEPTH_ROWS = [
    {"position": "GK", "cnt": 3},
    {"position": "DEF", "cnt": 8},
    {"position": "MID", "cnt": 8},
    {"position": "FWD", "cnt": 5},
]

_AI_ROWS = [
    {"team_name": "France", "cnt": 5},
    {"team_name": "Brazil", "cnt": 4},
]

_AI_PLAN_JSON = (
    '{"sql": "SELECT team_name, COUNT(*) AS cnt FROM `x.gold_player_stats`'
    ' WHERE position = \'FWD\' AND age < 22 GROUP BY team_name LIMIT 20",'
    ' "chart_type": "bar", "title": "Forwards Under 22 by Team"}'
)


# ---------------------------------------------------------------------------
# GET /charts/squad-age-profile
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_SQUAD_AGE_ROWS)
async def test_squad_age_profile_returns_200(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/charts/squad-age-profile")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_SQUAD_AGE_ROWS)
async def test_squad_age_profile_has_labels_and_data(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/charts/squad-age-profile")
    data = response.json()
    assert "labels" in data
    assert "data" in data
    assert "title" in data
    assert len(data["labels"]) == len(data["data"])
    assert len(data["labels"]) == 3


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_SQUAD_AGE_ROWS)
async def test_squad_age_profile_queries_gold_player_stats(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/charts/squad-age-profile")
    sql = mock_bq.call_args[0][0]
    assert "gold_player_stats" in sql
    assert "AVG" in sql.upper()


# ---------------------------------------------------------------------------
# GET /charts/top-teams  (kept from previous version)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_TEAM_ROWS)
async def test_top_teams_returns_200(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/charts/top-teams")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_TEAM_ROWS)
async def test_top_teams_has_labels_and_data(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/charts/top-teams")
    data = response.json()
    assert "labels" in data
    assert "data" in data
    assert "title" in data
    assert len(data["labels"]) == len(data["data"])


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_TEAM_ROWS)
async def test_top_teams_queries_gold_team_summary(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/charts/top-teams")
    sql = mock_bq.call_args[0][0]
    assert "gold_team_summary" in sql


# ---------------------------------------------------------------------------
# GET /charts/team-depth/{team_name}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_DEPTH_ROWS)
async def test_team_depth_returns_200(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/charts/team-depth/England")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_DEPTH_ROWS)
async def test_team_depth_has_labels_and_data(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/charts/team-depth/England")
    data = response.json()
    assert "labels" in data
    assert "data" in data
    assert "title" in data
    assert len(data["labels"]) == len(data["data"])


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_DEPTH_ROWS)
async def test_team_depth_queries_gold_player_stats(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/charts/team-depth/England")
    sql = mock_bq.call_args[0][0]
    assert "gold_player_stats" in sql
    assert "england" in sql.lower()


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_DEPTH_ROWS)
async def test_team_depth_title_includes_team_name(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/charts/team-depth/Germany")
    data = response.json()
    assert "Germany" in data["title"]


# ---------------------------------------------------------------------------
# POST /charts/ai-generate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("google.genai.Client")
@patch("src.utils.bq_client.bq.run_query", return_value=_AI_ROWS)
async def test_ai_generate_returns_200(mock_bq, mock_client_cls):
    mock_resp = MagicMock()
    mock_resp.text = _AI_PLAN_JSON
    mock_client_cls.return_value.models.generate_content.return_value = mock_resp

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/charts/ai-generate", json={"request": "forwards under 22"})
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("google.genai.Client")
@patch("src.utils.bq_client.bq.run_query", return_value=_AI_ROWS)
async def test_ai_generate_has_required_keys(mock_bq, mock_client_cls):
    mock_resp = MagicMock()
    mock_resp.text = _AI_PLAN_JSON
    mock_client_cls.return_value.models.generate_content.return_value = mock_resp

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/charts/ai-generate", json={"request": "forwards under 22"})
    data = response.json()
    assert "labels" in data
    assert "data" in data
    assert "chart_type" in data
    assert "title" in data


@pytest.mark.asyncio
@patch("google.genai.Client")
@patch("src.utils.bq_client.bq.run_query", return_value=_AI_ROWS)
async def test_ai_generate_chart_type_is_valid(mock_bq, mock_client_cls):
    mock_resp = MagicMock()
    mock_resp.text = _AI_PLAN_JSON
    mock_client_cls.return_value.models.generate_content.return_value = mock_resp

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/charts/ai-generate", json={"request": "test"})
    data = response.json()
    assert data["chart_type"] in ("bar", "line", "doughnut")


@pytest.mark.asyncio
@patch("google.genai.Client")
@patch("src.utils.bq_client.bq.run_query", return_value=_AI_ROWS)
async def test_ai_generate_labels_and_data_same_length(mock_bq, mock_client_cls):
    mock_resp = MagicMock()
    mock_resp.text = _AI_PLAN_JSON
    mock_client_cls.return_value.models.generate_content.return_value = mock_resp

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/charts/ai-generate", json={"request": "test"})
    data = response.json()
    assert len(data["labels"]) == len(data["data"])
