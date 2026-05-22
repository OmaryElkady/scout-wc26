import json
import logging
import sys
from typing import Any

import google.genai as genai
from google.genai import types

from src.agent import tools as agent_tools
from src.utils.config import config

logger = logging.getLogger(__name__)

_MODEL = "gemini-2.0-flash"
_MAX_TOOL_ROUNDS = 5

_SYSTEM_INSTRUCTION = (
    "You are an expert football scout analyzing data for the 2026 FIFA World Cup. "
    "Use the provided tools to query player and team data from the database. "
    "Base every answer on data returned by the tools. "
    "Be specific: include player names, ages, nationalities, positions, and team names."
)

_TOOL_FUNCTIONS = [
    agent_tools.query_players,
    agent_tools.query_team_summary,
    agent_tools.get_player_detail,
    agent_tools.get_top_players_by_position,
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
