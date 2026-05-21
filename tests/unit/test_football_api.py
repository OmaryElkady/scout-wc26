from unittest.mock import MagicMock, call, patch

import pytest

from src.utils.football_api import FootballAPIClient, _WORLD_CUP_LEAGUE_ID


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
    payload = {"standings": [{"teamId": 1}]}
    with patch("src.utils.football_api.requests.get", return_value=_mock_response(200, payload)):
        result = client._get("/some-endpoint")
    assert result == payload


def test_get_sends_rapidapi_headers():
    client = _make_client()
    with patch("src.utils.football_api.requests.get", return_value=_mock_response(200, {})):
        client._get("/endpoint")
    assert "x-rapidapi-key" in client._headers
    assert "x-rapidapi-host" in client._headers


# ---------------------------------------------------------------------------
# get_world_cup_standings — returns tuple (rows, team_ids)
# ---------------------------------------------------------------------------


def test_standings_returns_tuple_from_bronze_cache():
    client = _make_client()
    cached = [{"teamId": 10}, {"teamId": 20}]
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get") as mock_requests:
        mock_bq.table_exists.return_value = True
        mock_bq.run_query.return_value = cached

        rows, team_ids = client.get_world_cup_standings()

    assert rows == cached
    assert team_ids == [10, 20]
    mock_requests.assert_not_called()


def test_standings_calls_api_with_leagueid_param():
    client = _make_client()
    api_payload = {"standings": [{"teamId": 5}, {"teamId": 6}]}
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, api_payload)) as mock_get:
        mock_bq.table_exists.return_value = False

        rows, team_ids = client.get_world_cup_standings()

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["leagueid"] == _WORLD_CUP_LEAGUE_ID
    assert "leagueId" not in kwargs["params"]
    assert "league_id" not in kwargs["params"]
    assert rows == [{"teamId": 5}, {"teamId": 6}]
    assert team_ids == [5, 6]


def test_standings_returns_empty_team_ids_when_api_has_no_standings_key():
    client = _make_client()
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, {"status": "ok"})):
        mock_bq.table_exists.return_value = False

        rows, team_ids = client.get_world_cup_standings()

    assert rows == []
    assert team_ids == []


def test_standings_skips_rows_missing_teamId():
    client = _make_client()
    api_payload = {"standings": [{"teamId": 99}, {"points": 3}]}
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, api_payload)):
        mock_bq.table_exists.return_value = False

        _, team_ids = client.get_world_cup_standings()

    assert team_ids == [99]


# ---------------------------------------------------------------------------
# get_world_cup_fixtures
# ---------------------------------------------------------------------------


def test_fixtures_returns_bronze_cache():
    client = _make_client()
    cached = [{"matchId": "55"}]
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get") as mock_requests:
        mock_bq.table_exists.return_value = True
        mock_bq.run_query.return_value = cached

        result = client.get_world_cup_fixtures()

    assert result == cached
    mock_requests.assert_not_called()


def test_fixtures_calls_api_with_leagueid_param():
    client = _make_client()
    api_payload = {"matches": [{"matchId": "10"}]}
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, api_payload)) as mock_get:
        mock_bq.table_exists.return_value = False

        result = client.get_world_cup_fixtures()

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["leagueid"] == _WORLD_CUP_LEAGUE_ID
    assert "leagueId" not in kwargs["params"]
    assert result == [{"matchId": "10"}]


def test_fixtures_returns_empty_list_on_missing_matches_key():
    client = _make_client()
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, {})):
        mock_bq.table_exists.return_value = False

        result = client.get_world_cup_fixtures()

    assert result == []


# ---------------------------------------------------------------------------
# get_players_by_team
# ---------------------------------------------------------------------------


def test_players_by_team_returns_bronze_cache():
    client = _make_client()
    cached = [{"playerId": "77", "team_id": 5}]
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get") as mock_requests:
        mock_bq.table_exists.return_value = True
        mock_bq.run_query.return_value = cached

        result = client.get_players_by_team(5)

    assert result == cached
    mock_requests.assert_not_called()


def test_players_by_team_calls_api_with_teamid_param():
    client = _make_client()
    player = {"playerId": "1", "excludeFromRanking": False}
    api_payload = {"response": {"list": {"squad": [{"title": "attackers", "members": [player]}]}}}
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, api_payload)) as mock_get:
        mock_bq.table_exists.return_value = False

        result = client.get_players_by_team(42)

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["teamid"] == 42
    assert "teamId" not in kwargs["params"]
    assert "team_id" not in kwargs["params"]
    assert result == [player]


def test_players_by_team_returns_empty_list_on_missing_players_key():
    client = _make_client()
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, {})):
        mock_bq.table_exists.return_value = False

        result = client.get_players_by_team(1)

    assert result == []


def test_players_by_team_api_error_propagates():
    client = _make_client()
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(503)):
        mock_bq.table_exists.return_value = False

        with pytest.raises(RuntimeError, match="HTTP 503"):
            client.get_players_by_team(1)


# ---------------------------------------------------------------------------
# get_player_detail
# ---------------------------------------------------------------------------


def test_player_detail_returns_bronze_cache():
    client = _make_client()
    cached = [{"player_id": 99, "name": "Mbappe"}]
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get") as mock_requests:
        mock_bq.table_exists.return_value = True
        mock_bq.run_query.return_value = cached

        result = client.get_player_detail(99)

    assert result == cached[0]
    mock_requests.assert_not_called()


def test_player_detail_calls_api_with_playerid_param():
    client = _make_client()
    api_payload = {"player": {"player_id": 7, "name": "Ronaldo"}}
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, api_payload)) as mock_get:
        mock_bq.table_exists.return_value = False

        result = client.get_player_detail(7)

    _, kwargs = mock_get.call_args
    assert kwargs["params"]["playerid"] == 7
    assert "playerId" not in kwargs["params"]
    assert "player_id" not in kwargs["params"]
    assert result == {"player_id": 7, "name": "Ronaldo"}


def test_player_detail_returns_empty_dict_on_missing_player_key():
    client = _make_client()
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, {})):
        mock_bq.table_exists.return_value = False

        result = client.get_player_detail(1)

    assert result == {}


def test_player_detail_falls_through_to_api_on_empty_bronze_cache():
    client = _make_client()
    api_payload = {"player": {"player_id": 99, "name": "Test"}}
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, api_payload)) as mock_requests:
        mock_bq.table_exists.return_value = True
        mock_bq.run_query.return_value = []  # LIMIT 1 returns nothing → cache miss

        result = client.get_player_detail(99)

    mock_requests.assert_called_once()
    assert result == {"player_id": 99, "name": "Test"}


# ---------------------------------------------------------------------------
# get_all_world_cup_players — orchestration
# ---------------------------------------------------------------------------


def test_all_players_returns_bronze_cache():
    client = _make_client()
    cached = [{"playerId": "1"}, {"playerId": "2"}]
    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get") as mock_requests:
        mock_bq.table_exists.return_value = True
        mock_bq.run_query.return_value = cached

        result = client.get_all_world_cup_players()

    assert result == cached
    mock_requests.assert_not_called()


def _squad(members: list[dict]) -> dict:
    return {"response": {"list": {"squad": [{"title": "attackers", "members": members}]}}}


def test_all_players_calls_fixtures_then_per_team():
    client = _make_client()
    fixtures_payload = {
        "matches": [
            {"home": {"id": "10", "name": "Team A", "score": 1}, "away": {"id": "20", "name": "Team B", "score": 0}},
        ]
    }
    p_a = {"playerId": "A", "excludeFromRanking": False}
    p_b = {"playerId": "B", "excludeFromRanking": False}
    p_c = {"playerId": "C", "excludeFromRanking": False}
    team10_payload = _squad([p_a])
    team20_payload = _squad([p_b, p_c])

    responses = [
        _mock_response(200, fixtures_payload),
        _mock_response(200, team10_payload),
        _mock_response(200, team20_payload),
    ]

    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", side_effect=responses):
        mock_bq.table_exists.return_value = False
        mock_bq.run_query.return_value = []

        result = client.get_all_world_cup_players()

    assert sorted(result, key=lambda p: p["playerId"]) == [p_a, p_b, p_c]


def test_all_players_returns_empty_list_when_no_teams():
    client = _make_client()
    fixtures_payload = {"matches": []}

    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", return_value=_mock_response(200, fixtures_payload)):
        mock_bq.table_exists.return_value = False
        mock_bq.run_query.return_value = []

        result = client.get_all_world_cup_players()

    assert result == []


def test_all_players_flattens_results_across_teams():
    client = _make_client()
    fixtures_payload = {
        "matches": [
            {"home": {"id": "1", "name": "Team A", "score": 1}, "away": {"id": "2", "name": "Team B", "score": 0}},
            {"home": {"id": "2", "name": "Team B", "score": 2}, "away": {"id": "3", "name": "Team C", "score": 1}},
        ]
    }
    team_payloads = [
        _squad([{"playerId": str(i), "excludeFromRanking": False} for i in range(3)]),
        _squad([{"playerId": str(i), "excludeFromRanking": False} for i in range(3, 5)]),
        _squad([]),
    ]

    responses = [_mock_response(200, fixtures_payload)] + [
        _mock_response(200, p) for p in team_payloads
    ]

    with patch("src.utils.football_api.bq") as mock_bq, \
         patch("src.utils.football_api.requests.get", side_effect=responses):
        mock_bq.table_exists.return_value = False
        mock_bq.run_query.return_value = []

        result = client.get_all_world_cup_players()

    assert len(result) == 5
