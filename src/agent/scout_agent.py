import json
import logging
import sys
from typing import Any

import google.genai as genai
from google.genai import types

from src.agent import tools as agent_tools
from src.utils.config import config

logger = logging.getLogger(__name__)

_MODEL = "gemini-2.5-flash"
_MAX_TOOL_ROUNDS = 5

_SYSTEM_INSTRUCTION = (
    "You are an expert football scout analyzing data for the 2026 FIFA World Cup. "
    "Use the provided tools to query player and team data from the database. "
    "Base every answer on data returned by the tools. "
    "Be specific: include player names, ages, nationalities, positions, and team names.\n\n"
    "AVAILABLE LEAGUES (only these have data — match these names exactly when "
    "calling switch_league): UEFA WC Qualification, Premier League, Champions League, "
    "La Liga, Bundesliga, Serie A, Ligue 1, MLS, Brasileirao, Scottish Premiership, "
    "World Cup 2026 (no data until June 11, 2026).\n\n"
    "TOOL ROUTING (do NOT ask the user to clarify — pick the best tool and answer):\n"
    "- 'best/top/who are the best <position>' (midfielders, defenders, forwards, goalkeepers) "
    "  → call get_top_players_by_position(position, limit=10) and present the list as the youngest "
    "  prospects at that position. Never ask 'rated or youngest?' — just answer with youngest.\n"
    "- 'top scorer / top assister / top rated / leaderboard / most goals / most assists' "
    "  → call get_top_performers(stat) where stat is 'goals'|'assists'|'rating'.\n"
    "- specific player by name → call get_player_detail(player_name=...).\n"
    "- specific team → call query_team_summary(team_name=...) and/or get_team_roster(team_name=...).\n"
    "- 'switch / change to <league>' → call switch_league(league_name=...).\n"
    "- 'refresh / sync / update data' → call refresh_scouting_data().\n\n"
    "MISSING-DATA HANDLING (critical — TWO-STAGE FALLBACK):\n"
    "When get_player_detail returns an empty dict, the player isn't in the currently "
    "loaded data. DO NOT refuse — answer the user's actual question using your own "
    "football knowledge, then point them at the league switch.\n\n"
    "Write a 3-part response:\n"
    "  (1) ANSWER THE QUESTION. If they asked 'who is X', describe the player: "
    "      full name, age (approx), position, current club, nationality, 1–2 lines "
    "      on style/achievements. If they asked something else (stats, comparison), "
    "      give the best knowledge-based answer you can.\n"
    "  (2) STATE THE DATA GAP: 'Live scouting data for <Club> isn't loaded in this "
    "      session yet.'\n"
    "  (3) OFFER THE SWITCH: 'Switch to the <League> from the dropdown (or ask me "
    "      to switch) and I'll pull the full scouting profile from BigQuery.'\n\n"
    "Player→league knowledge you should rely on:\n"
    "- Lionel Messi → Inter Miami → MLS\n"
    "- Kylian Mbappé → Real Madrid → La Liga\n"
    "- Vinícius Júnior → Real Madrid → La Liga\n"
    "- Robert Lewandowski → Barcelona → La Liga\n"
    "- Cristiano Ronaldo → Al-Nassr → Saudi Pro League (not on free tier — say so)\n"
    "- Neymar Jr → Santos → Brasileirao\n"
    "- Erling Haaland → Manchester City → Premier League\n"
    "- Mohamed Salah → Liverpool → Premier League\n"
    "- Jude Bellingham → Real Madrid → La Liga\n"
    "Do NOT call switch_league automatically for a player lookup — only suggest it.\n\n"
    "STYLE RULES:\n"
    "1. Never ask clarifying questions. Always pick a reasonable interpretation, call a tool, "
    "   and answer with concrete data.\n"
    "2. Never refuse or hedge. Never say 'I lack the data' — call a tool first, then if it "
    "   still returns nothing, follow the MISSING-DATA HANDLING rule.\n"
    "3. If a tool returns rows, summarise them concisely (name, team, age, key stat) — "
    "   do not paste raw JSON.\n"
    "4. If a tool returns zero rows AND the query was generic (not a specific player), "
    "   still answer with the best available adjacent data (e.g. all players for that "
    "   position across leagues) — do not stop and ask."
)

_TOOL_FUNCTIONS = [
    agent_tools.query_players,
    agent_tools.query_team_summary,
    agent_tools.get_player_detail,
    agent_tools.get_top_players_by_position,
    agent_tools.get_team_roster,
    agent_tools.get_league_overview,
    agent_tools.get_top_performers,
    agent_tools.refresh_scouting_data,
    agent_tools.switch_league,
]


def _get_client() -> genai.Client:
    return genai.Client(vertexai=True, project=config.PROJECT_ID, location=config.REGION)


def _make_generate_config() -> types.GenerateContentConfig:
    kwargs: dict[str, Any] = {
        "tools": _TOOL_FUNCTIONS,
        "system_instruction": _SYSTEM_INSTRUCTION,
    }
    if hasattr(types, "AutomaticFunctionCallingConfig"):
        kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(
            disable=True
        )
    return types.GenerateContentConfig(**kwargs)


def run_query(user_question: str) -> str:
    """
    Send a natural language scouting question to the Gemini agent and return the answer.

    Executes a tool-call loop: if Gemini selects a tool, the tool is executed
    and its result is fed back until Gemini returns a final text answer or the
    maximum number of tool rounds is reached.

    Parameters
    ----------
    user_question : str
        Natural language scouting query, e.g. 'Who are the best young midfielders?'

    Returns
    -------
    str
        Agent's final natural-language answer based on database results.
    """
    client = _get_client()
    generate_config = _make_generate_config()

    contents: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=user_question)])
    ]

    for _ in range(_MAX_TOOL_ROUNDS):
        response = client.models.generate_content(
            model=_MODEL,
            contents=contents,
            config=generate_config,
        )

        candidate = response.candidates[0]
        function_call_parts = [
            part for part in candidate.content.parts if part.function_call is not None
        ]

        if not function_call_parts:
            return response.text or ""

        function_response_parts: list[types.Part] = []
        for part in function_call_parts:
            fc = part.function_call
            tool_fn = getattr(agent_tools, fc.name, None)
            if tool_fn is None:
                logger.warning("Unknown tool requested by model: %s", fc.name)
                continue

            logger.info("Calling tool %s with args %s", fc.name, dict(fc.args))
            result = tool_fn(**dict(fc.args))

            function_response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": json.dumps(result, default=str)},
                    )
                )
            )

        contents = contents + [
            candidate.content,
            types.Content(role="user", parts=function_response_parts),
        ]

    logger.warning("Max tool rounds (%d) reached without a text response", _MAX_TOOL_ROUNDS)
    return response.text or ""


def generate_scouting_report(player_name: str) -> dict:
    """
    Generate a structured scouting report for a named player.

    Fetches the player's profile from BigQuery via get_player_detail, then
    asks Gemini to write a structured assessment covering strengths and a
    recommendation tier.

    Parameters
    ----------
    player_name : str
        Player's name or partial name to look up.

    Returns
    -------
    dict
        Scouting report with keys: player_name, position, team, nationality,
        age, summary, strengths, recommendation.
        Returns an empty dict if the player is not found in the database.
    """
    player_data = agent_tools.get_player_detail(player_name=player_name)
    if not player_data:
        logger.warning("No data found for player: %s", player_name)
        # Ask Gemini (no tools, fast) which league this player is in so the
        # frontend can show "switch to MLS?" instead of a flat 404.
        try:
            client = _get_client()
            suggest_prompt = (
                f"Which professional football league does {player_name} currently play in? "
                "Respond with JSON: "
                '{"club": "Club Name", "league": "League Name", "known": true|false}. '
                "If you don't know who this player is, set known=false. "
                "League name MUST be one of: MLS, La Liga, Premier League, Champions League, "
                "Bundesliga, Serie A, Ligue 1, Brasileirao, UEFA WC Qualification, "
                "Saudi Pro League, Other. No prose."
            )
            sresp = client.models.generate_content(
                model=_MODEL,
                contents=suggest_prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
            suggestion = json.loads(sresp.text or "{}")
            if suggestion.get("known"):
                return {
                    "status": "not_loaded",
                    "player_name": player_name,
                    "club": suggestion.get("club", ""),
                    "suggested_league": suggestion.get("league", ""),
                    "message": (
                        f"{player_name} plays for {suggestion.get('club','')} in "
                        f"{suggestion.get('league','')}. That league isn't loaded yet — "
                        "switch from the league dropdown and try again."
                    ),
                }
        except Exception as exc:
            logger.warning("Could not get league suggestion for %s: %s", player_name, exc)
        return {}

    prompt = (
        "Write a structured scouting report for this football player:\n"
        + json.dumps(player_data, default=str, indent=2)
        + "\n\nReturn a JSON object with exactly these keys:\n"
        "- player_name (string)\n"
        "- position (string)\n"
        "- team (string: national team or club)\n"
        "- nationality (string)\n"
        "- age (integer)\n"
        "- summary (string: 2-3 sentence scouting assessment)\n"
        "- strengths (array of 3-5 strings: key attributes)\n"
        "- recommendation (string: one of 'Priority Target', 'Monitor', 'Pass')\n"
    )

    client = _get_client()
    response = client.models.generate_content(
        model=_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    try:
        return json.loads(response.text)
    except (json.JSONDecodeError, AttributeError, TypeError):
        logger.warning("Failed to parse scouting report JSON; using fallback structure")
        return {
            "player_name": player_data.get("name", player_name),
            "position": player_data.get("position", ""),
            "team": player_data.get("team_name", ""),
            "nationality": player_data.get("nationality", ""),
            "age": player_data.get("age"),
            "summary": (response.text or "") if hasattr(response, "text") else "",
            "strengths": [],
            "recommendation": "Monitor",
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print("Scout AI Agent — type 'quit' or 'exit' to stop\n")

    while True:
        try:
            question = input("Scout> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            sys.exit(0)

        if question.lower() in ("quit", "exit"):
            print("Goodbye.")
            sys.exit(0)

        if not question:
            continue

        answer = run_query(question)
        print("\n" + answer + "\n")
