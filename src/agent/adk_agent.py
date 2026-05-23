from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from src.agent import tools as agent_tools

Scout = Agent(
    name="Scout",
    model="gemini-2.5-flash",
    description=(
        "AI-powered World Cup scouting agent. Answers natural language questions "
        "about players, teams, and match data. Can refresh the data pipeline."
    ),
    instruction=(
        "You are Scout, an AI football scouting assistant for the 2026 World Cup. "
        "You have access to a BigQuery database with player profiles, team standings, "
        "and match fixtures.\n\n"
        "When a user asks about players, use query_players or get_player_detail. "
        "When asked about teams, use query_team_summary. "
        "When asked for top players by position, use get_top_players_by_position. "
        "When asked to refresh or update data, use refresh_scouting_data.\n\n"
        "Always provide specific player names, ages, and nationalities in your responses. "
        "Be concise but informative, like a real football scout."
    ),
    tools=[
        FunctionTool(agent_tools.query_players),
        FunctionTool(agent_tools.query_team_summary),
        FunctionTool(agent_tools.get_player_detail),
        FunctionTool(agent_tools.get_top_players_by_position),
        FunctionTool(agent_tools.refresh_scouting_data),
    ],
)
