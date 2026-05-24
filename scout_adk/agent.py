from google.adk.agents import Agent

from src.agent import tools as agent_tools
from src.utils.config import config

# ADK routes to Vertex AI only when the model starts with "projects/".
# Using just "gemini-2.5-flash" makes ADK call the Gemini API and demand
# GOOGLE_API_KEY, which we don't use — we authenticate via ADC + Vertex AI.
_VERTEX_MODEL = (
    f"projects/{config.PROJECT_ID}/locations/{config.REGION}"
    "/publishers/google/models/gemini-2.5-flash"
)

root_agent = Agent(
    name="scout",
    model=_VERTEX_MODEL,
    description=(
        "AI-powered World Cup scouting agent. Answers natural language questions "
        "about players, teams, and match data for the 2026 FIFA World Cup. "
        "Can refresh the data pipeline via Fivetran."
    ),
    instruction=(
        "You are Scout, an AI football scouting assistant for the 2026 World Cup. "
        "You have access to a BigQuery database with 1,391 player profiles across 50 "
        "national teams, team standings, and match fixtures from UEFA World Cup Qualification.\n\n"
        "When asked about players use query_players or get_player_detail. "
        "When asked about teams use query_team_summary. "
        "When asked for top players by position use get_top_players_by_position. "
        "When asked to refresh or update data use refresh_scouting_data.\n\n"
        "When asked broadly about teams or performance with no specific team mentioned, "
        "call query_team_summary with no arguments to get all teams ranked. "
        "When asked what data or leagues are available, call get_league_overview. "
        "When asked about a team's players or squad, call get_team_roster with the team name.\n\n"
        "When the user asks to change league, switch competition, or view a different tournament, "
        "call switch_league() with the league name. You CAN switch leagues — this is a supported "
        "action. Available leagues include: UEFA WC Qualification (current), World Cup 2026, "
        "Premier League, Champions League, La Liga, Bundesliga, Serie A, Ligue 1.\n\n"
        "Always provide specific names, ages, and nationalities. "
        "Be concise but informative like a real football scout."
    ),
    tools=[
        agent_tools.query_players,
        agent_tools.query_team_summary,
        agent_tools.get_player_detail,
        agent_tools.get_top_players_by_position,
        agent_tools.get_team_roster,
        agent_tools.get_league_overview,
        agent_tools.refresh_scouting_data,
        agent_tools.switch_league,
    ],
)
