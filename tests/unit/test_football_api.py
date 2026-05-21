from unittest.mock import MagicMock, patch

import pytest

from src.utils.football_api import FootballAPIClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client() -> FootballAPIClient:
    return FootballAPIClient()


def _mock_response(status: int = 200, body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = body or {}
    resp.text = str(body or {})
    return resp


# ---------------------------------------------------------------------------
# _get — low-level HTTP helper
# ---------------------------------------------------------------------------


def test_get_raises_on_non_200():
    client = _make_client()
    with patch("src.utils.football_api.requests.get", return_value=_mock_response(429)):
        with pytest.raises(RuntimeError, match="HTTP 429"):
            client._get("/some-endpoint")


def test_get_returns_parsed_json_on_200():
    client = _make_client()
    payload = {"response": [{"id": 1}]}
    with patch("src.utils.football_api.requests.get", return_value=_mock_response(200, payload)):
        result = client._get("/some-endpoint")
    assert result == payload


def test_get_sends_rapidapi_headers():
    client = _make_client()
    with patch("src.utils.football_api.requests.get", return_value=_mock_response(200, {})) as mock_get:
        client._get("/endpoint")
    _, kwargs = mock_get.call_args
    headers = kwargs.get("headers") or mock_get.call_args[0][1] if len(mock_get.call_args[0]) > 1 else mock_get.call_args[1].get("headers")
    assert "x-rapidapi-key" in client._headers
    assert "x-rapidapi-host" in client._headers


# ---------------------------------------------------------------------------
# get_world_cup_players
# ---------------------------------------------------------------------------


def test_players_returns_bronze_cache_when_available():
    client = _make_client()
    cached = [{"player_id": "99", "name": "Mbappe", "season": 2026}]
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get") as mock_requests:
        mock_bq.table_exists.return_value = True
        mock_bq.run_query.return_value = cached

        result = client.get_world_cup_players(season=2026)

    assert result == cached
    mock_requests.assert_not_called()


def test_players_calls_api_when_bronze_table_missing():
    client = _make_client()
    api_payload = {"response": [{"player_id": "1"}]}
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, api_payload)):
        mock_bq.table_exists.return_value = False

        result = client.get_world_cup_players(season=2026)

    assert result == [{"player_id": "1"}]
    mock_bq.run_query.assert_not_called()


def test_players_calls_api_when_bronze_table_empty():
    client = _make_client()
    api_payload = {"response": [{"player_id": "2"}]}
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, api_payload)):
        mock_bq.table_exists.return_value = True
        mock_bq.run_query.return_value = []  # LIMIT 1 returns nothing → cache miss

        result = client.get_world_cup_players(season=2026)

    assert result == [{"player_id": "2"}]


def test_players_returns_empty_list_when_api_has_no_response_key():
    client = _make_client()
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, {"status": "ok"})):
        mock_bq.table_exists.return_value = False

        result = client.get_world_cup_players(season=2026)

    assert result == []


def test_players_api_raises_propagates():
    client = _make_client()
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(503)):
        mock_bq.table_exists.return_value = False

        with pytest.raises(RuntimeError, match="HTTP 503"):
            client.get_world_cup_players(season=2026)


# ---------------------------------------------------------------------------
# get_world_cup_fixtures
# ---------------------------------------------------------------------------


def test_fixtures_returns_bronze_cache_when_available():
    client = _make_client()
    cached = [{"fixture_id": "55"}]
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get") as mock_requests:
        mock_bq.table_exists.return_value = True
        mock_bq.run_query.return_value = cached

        result = client.get_world_cup_fixtures(season=2026)

    assert result == cached
    mock_requests.assert_not_called()


def test_fixtures_calls_api_on_cache_miss():
    client = _make_client()
    api_payload = {"response": [{"fixture_id": "10"}]}
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, api_payload)):
        mock_bq.table_exists.return_value = False

        result = client.get_world_cup_fixtures(season=2026)

    assert result == [{"fixture_id": "10"}]


# ---------------------------------------------------------------------------
# get_world_cup_standings
# ---------------------------------------------------------------------------


def test_standings_returns_bronze_cache_when_available():
    client = _make_client()
    cached = [{"team": "Brazil", "points": 9}]
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get") as mock_requests:
        mock_bq.table_exists.return_value = True
        mock_bq.run_query.return_value = cached

        result = client.get_world_cup_standings(season=2026)

    assert result == cached
    mock_requests.assert_not_called()


def test_standings_calls_api_on_cache_miss():
    client = _make_client()
    api_payload = {"response": [{"team": "France"}]}
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, api_payload)):
        mock_bq.table_exists.return_value = False

        result = client.get_world_cup_standings(season=2026)

    assert result == [{"team": "France"}]
