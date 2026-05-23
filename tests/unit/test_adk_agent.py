from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from src.agent.adk_agent import Scout

_EXPECTED_TOOLS = {
    "query_players",
    "query_team_summary",
    "get_player_detail",
    "get_top_players_by_position",
    "refresh_scouting_data",
}


def test_scout_is_adk_agent():
    assert isinstance(Scout, Agent)


def test_scout_name():
    assert Scout.name == "Scout"


def test_scout_model():
    assert Scout.model == "gemini-2.5-flash"


def test_scout_has_five_tools():
    assert len(Scout.tools) == 5


def test_scout_all_tools_are_function_tools():
    assert all(isinstance(t, FunctionTool) for t in Scout.tools)


def test_scout_tool_names_match_expected():
    registered = {t.name for t in Scout.tools}
    assert registered == _EXPECTED_TOOLS
