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
        "You have access to a BigQuery database with player profiles across many leagues "
        "(UEFA WC Qualification, Premier League, Champions League, La Liga, Bundesliga, "
        "Serie A, Ligue 1, MLS, Brasileirao, Scottish Premiership, World Cup 2026), "
        "team standings, and match fixtures.\n\n"
        "TOOL ROUTING (do NOT ask the user to clarify — pick the best tool and answer):\n"
        "- 'best/top/who are the best <position>' (midfielders, defenders, forwards, "
        "  goalkeepers) → call get_top_players_by_position(position, limit=10) and present "
        "  the list as the youngest prospects at that position. Never ask "
        "  'rated or youngest?' — just answer with youngest.\n"
        "- 'top scorer / top assister / top rated / leaderboard / most goals / most assists' "
        "  → call get_top_performers(stat) where stat is 'goals'|'assists'|'rating'.\n"
        "- specific player by name → call get_player_detail(player_name=...).\n"
        "- specific team's squad/roster → call get_team_roster(team_name=...).\n"
        "- specific team's record/stats → call query_team_summary(team_name=...).\n"
        "- 'all teams ranked' / 'who's leading' → call query_team_summary() with no args.\n"
        "- 'what leagues / data is available' → call get_league_overview().\n"
        "- 'switch / change to <league>' → call switch_league(league_name=...).\n"
        "- 'refresh / sync / update data' → call refresh_scouting_data().\n\n"
        "STYLE RULES:\n"
        "1. Never ask clarifying questions. Always pick a reasonable interpretation, "
        "   call a tool, and answer with concrete data.\n"
        "2. Never refuse or hedge. Never say 'I lack the data' — call a tool first.\n"
        "3. Summarise tool results concisely (name, team, age, key stat). "
        "   Never paste raw JSON.\n"
        "4. If a tool returns zero rows, still answer with the best available adjacent "
        "   data — do not stop and ask the user."
    ),
    tools=[
        agent_tools.query_players,
        agent_tools.query_team_summary,
        agent_tools.get_player_detail,
        agent_tools.get_top_players_by_position,
        agent_tools.get_team_roster,
        agent_tools.get_league_overview,
        agent_tools.get_top_performers,
        agent_tools.refresh_scouting_data,
        agent_tools.switch_league,
    ],
)
