from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from src.api.main import app

_POS_ROWS = [
    {"position": "DEF", "cnt": 452},
    {"position": "FWD", "cnt": 321},
    {"position": "GK", "cnt": 169},
    {"position": "MID", "cnt": 428},
    {"position": "UNKNOWN", "cnt": 21},
]

_TEAM_ROWS = [
    {"team_name": "France", "points": 30},
    {"team_name": "Brazil", "points": 28},
    {"team_name": "Germany", "points": 25},
]

_AGE_ROWS = [
    {"age": 22, "cnt": 15},
    {"age": 23, "cnt": 30},
    {"age": 24, "cnt": 45},
]

_NAT_ROWS = [
    {"nationality": "French", "cnt": 23},
    {"nationality": "Brazilian", "cnt": 22},
    {"nationality": "German", "cnt": 20},
]


# ---------------------------------------------------------------------------
# GET /charts/position-breakdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_POS_ROWS)
async def test_position_breakdown_returns_200(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/charts/position-breakdown")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_POS_ROWS)
async def test_position_breakdown_has_labels_and_data(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/charts/position-breakdown")
    data = response.json()
    assert "labels" in data
    assert "data" in data
    assert "title" in data
    assert isinstance(data["labels"], list)
    assert isinstance(data["data"], list)
    assert len(data["labels"]) == len(data["data"])


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_POS_ROWS)
async def test_position_breakdown_queries_gold_player_stats(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/charts/position-breakdown")
    sql = mock_bq.call_args[0][0]
    assert "gold_player_stats" in sql


# ---------------------------------------------------------------------------
# GET /charts/top-teams
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
# GET /charts/age-distribution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_AGE_ROWS)
async def test_age_distribution_returns_200(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/charts/age-distribution")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_AGE_ROWS)
async def test_age_distribution_has_labels_and_data(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/charts/age-distribution")
    data = response.json()
    assert "labels" in data
    assert "data" in data
    assert "title" in data
    assert len(data["labels"]) == len(data["data"])


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_AGE_ROWS)
async def test_age_distribution_queries_gold_player_stats(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/charts/age-distribution")
    sql = mock_bq.call_args[0][0]
    assert "gold_player_stats" in sql


# ---------------------------------------------------------------------------
# GET /charts/nationality-breakdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_NAT_ROWS)
async def test_nationality_breakdown_returns_200(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/charts/nationality-breakdown")
    assert response.status_code == 200


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_NAT_ROWS)
async def test_nationality_breakdown_has_labels_and_data(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/charts/nationality-breakdown")
    data = response.json()
    assert "labels" in data
    assert "data" in data
    assert "title" in data
    assert len(data["labels"]) == len(data["data"])


@pytest.mark.asyncio
@patch("src.utils.bq_client.bq.run_query", return_value=_NAT_ROWS)
async def test_nationality_breakdown_queries_gold_player_stats(mock_bq):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.get("/charts/nationality-breakdown")
    sql = mock_bq.call_args[0][0]
    assert "gold_player_stats" in sql
