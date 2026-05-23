from google.adk.agents import Agent

from scout_adk.agent import root_agent

_EXPECTED_TOOLS = {
    "query_players",
    "query_team_summary",
    "get_player_detail",
    "get_top_players_by_position",
    "get_team_roster",
    "get_league_overview",
    "refresh_scouting_data",
}


def test_root_agent_is_adk_agent():
    assert isinstance(root_agent, Agent)


def test_root_agent_name():
    assert root_agent.name == "scout"


def test_root_agent_has_seven_tools():
    assert len(root_agent.tools) == 7


def test_root_agent_tool_names_match_expected():
    registered = {getattr(t, "name", getattr(t, "__name__", None)) for t in root_agent.tools}
    assert registered == _EXPECTED_TOOLS
