import json
from unittest.mock import MagicMock, patch

from src.agent.scout_agent import generate_scouting_report, run_query


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _text_response(text: str) -> MagicMock:
    """Mock Gemini response containing only a text part (no function calls)."""
    part = MagicMock()
    part.function_call = None

    candidate = MagicMock()
    candidate.content.parts = [part]

    response = MagicMock()
    response.text = text
    response.candidates = [candidate]
    return response


def _tool_call_response(tool_name: str, tool_args: dict) -> MagicMock:
    """Mock Gemini response containing a single function call part."""
    fc = MagicMock()
    fc.name = tool_name
    fc.args = tool_args

    part = MagicMock()
    part.function_call = fc

    candidate = MagicMock()
    candidate.content.parts = [part]
    candidate.content.role = "model"

    response = MagicMock()
    response.candidates = [candidate]
    return response


# ---------------------------------------------------------------------------
# run_query: direct text response (no tool calls)
# ---------------------------------------------------------------------------


@patch("src.agent.scout_agent.genai.Client")
def test_run_query_returns_text_when_no_tool_calls(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.models.generate_content.return_value = _text_response(
        "Mbappe is the top scorer."
    )

    result = run_query("Who is the top scorer?")

    assert result == "Mbappe is the top scorer."
    assert mock_client.models.generate_content.call_count == 1


@patch("src.agent.scout_agent.genai.Client")
def test_run_query_passes_user_question_to_model(mock_client_class):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.models.generate_content.return_value = _text_response("Answer.")

    run_query("Find young midfielders")

    call_kwargs = mock_client.models.generate_content.call_args.kwargs
    contents = call_kwargs["contents"]
    assert any("Find young midfielders" in str(c) for c in contents)


# ---------------------------------------------------------------------------
# run_query: single tool call followed by text response
# ---------------------------------------------------------------------------


@patch("src.agent.scout_agent.agent_tools.query_players")
@patch("src.agent.scout_agent.genai.Client")
def test_run_query_executes_tool_call(mock_client_class, mock_query_players):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.models.generate_content.side_effect = [
        _tool_call_response("query_players", {"position": "Forward"}),
        _text_response("Here are the top forwards."),
    ]
    mock_query_players.return_value = [{"name": "Mbappe", "position": "Forward"}]

    result = run_query("Show me the best forwards")

    assert result == "Here are the top forwards."
    mock_query_players.assert_called_once_with(position="Forward")


@patch("src.agent.scout_agent.agent_tools.query_players")
@patch("src.agent.scout_agent.genai.Client")
def test_run_query_calls_model_twice_for_one_tool_round(mock_client_class, mock_query_players):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.models.generate_content.side_effect = [
        _tool_call_response("query_players", {"nationality": "French"}),
        _text_response("The French players are excellent."),
    ]
    mock_query_players.return_value = []

    run_query("Tell me about French players")

    assert mock_client.models.generate_content.call_count == 2


@patch("src.agent.scout_agent.agent_tools.query_players")
@patch("src.agent.scout_agent.genai.Client")
def test_run_query_sends_tool_result_in_second_call(mock_client_class, mock_query_players):
    """After a tool call, the second model request must include the function response."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_client.models.generate_content.side_effect = [
        _tool_call_response("query_players", {"position": "Defender"}),
        _text_response("Here are the defenders."),
    ]
    mock_query_players.return_value = [{"name": "Ramos"}]

    run_query("List the defenders")

    second_call_contents = mock_client.models.generate_content.call_args_list[1].kwargs[
        "contents"
    ]
    # Original user turn + model fc turn + function response turn = at least 3 items
    assert len(second_call_contents) >= 3


# ---------------------------------------------------------------------------
# generate_scouting_report
# ---------------------------------------------------------------------------


@patch("src.agent.scout_agent.agent_tools.get_player_detail")
@patch("src.agent.scout_agent.genai.Client")
def test_generate_scouting_report_returns_required_keys(mock_client_class, mock_get_detail):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_get_detail.return_value = {
        "player_id": "1",
        "name": "Kylian Mbappe",
        "position": "Forward",
        "team_name": "France",
        "nationality": "French",
        "age": 25,
    }
    report_data = {
        "player_name": "Kylian Mbappe",
        "position": "Forward",
        "team": "France",
        "nationality": "French",
        "age": 25,
        "summary": "World-class striker with exceptional pace and finishing.",
        "strengths": ["Pace", "Finishing", "Dribbling"],
        "recommendation": "Priority Target",
    }
    mock_response = MagicMock()
    mock_response.text = json.dumps(report_data)
    mock_client.models.generate_content.return_value = mock_response

    report = generate_scouting_report("Kylian Mbappe")

    required_keys = {
        "player_name",
        "position",
        "team",
        "nationality",
        "age",
        "summary",
        "strengths",
        "recommendation",
    }
    assert required_keys.issubset(set(report.keys()))
    assert report["player_name"] == "Kylian Mbappe"
    assert isinstance(report["strengths"], list)


@patch("src.agent.scout_agent.agent_tools.get_player_detail")
def test_generate_scouting_report_unknown_player_returns_empty_dict(mock_get_detail):
    mock_get_detail.return_value = {}
    assert generate_scouting_report("Unknown Player XYZ") == {}


@patch("src.agent.scout_agent.agent_tools.get_player_detail")
@patch("src.agent.scout_agent.genai.Client")
def test_generate_scouting_report_invalid_json_returns_fallback(mock_client_class, mock_get_detail):
    """Malformed JSON from Gemini must produce a valid fallback dict, not raise."""
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_get_detail.return_value = {
        "name": "Test Player",
        "position": "Midfielder",
        "team_name": "Test FC",
        "nationality": "Dutch",
        "age": 22,
    }
    mock_response = MagicMock()
    mock_response.text = "This is not valid JSON at all."
    mock_client.models.generate_content.return_value = mock_response

    report = generate_scouting_report("Test Player")

    assert "player_name" in report
    assert "recommendation" in report
    assert report["recommendation"] == "Monitor"
    assert report["player_name"] == "Test Player"


@patch("src.agent.scout_agent.agent_tools.get_player_detail")
@patch("src.agent.scout_agent.genai.Client")
def test_generate_scouting_report_calls_get_player_detail(mock_client_class, mock_get_detail):
    mock_client = MagicMock()
    mock_client_class.return_value = mock_client
    mock_get_detail.return_value = {"name": "Vinicius Jr", "age": 23}
    mock_response = MagicMock()
    mock_response.text = json.dumps(
        {
            "player_name": "Vinicius Jr",
            "position": "Forward",
            "team": "Brazil",
            "nationality": "Brazilian",
            "age": 23,
            "summary": "Electric winger.",
            "strengths": ["Pace"],
            "recommendation": "Priority Target",
        }
    )
    mock_client.models.generate_content.return_value = mock_response

    generate_scouting_report("Vinicius")

    mock_get_detail.assert_called_once_with(player_name="Vinicius")
