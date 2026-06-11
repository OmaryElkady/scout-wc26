import logging
import os
import pathlib
import re
import threading
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response

from src.agent import scout_agent
from src.agent import tools as agent_tools
from src.api.models import (
    ChartRequest,
    PlayerListResponse,
    QueryRequest,
    QueryResponse,
    ReportResponse,
    SwitchLeagueRequest,
    TeamListResponse,
)
from src.utils.bq_client import bq
from src.utils.config import config
from src.utils.text_normalize import unaccent, unaccent_sql

logger = logging.getLogger(__name__)


def _esc(s: str) -> str:
    return s.replace("'", "''")


def _normalize_match(m: dict, *, is_live: bool) -> dict:
    home = m.get("home") or {}
    away = m.get("away") or {}
    score_obj = m.get("score") if isinstance(m.get("score"), dict) else {}
    home_name = home.get("name") or m.get("homeTeam") or m.get("home_team") or ""
    away_name = away.get("name") or m.get("awayTeam") or m.get("away_team") or ""
    home_score = home.get("score") if home.get("score") is not None else score_obj.get("home")
    away_score = away.get("score") if away.get("score") is not None else score_obj.get("away")
    status = m.get("status") or m.get("state") or ("LIVE" if is_live else "NS")
    match_date = m.get("date") or m.get("matchDate") or m.get("startDate") or ""
    match_time = m.get("time") or m.get("matchTime") or m.get("startTime") or ""
    return {
        "home_team": str(home_name),
        "away_team": str(away_name),
        "home_score": int(home_score) if home_score is not None else None,
        "away_score": int(away_score) if away_score is not None else None,
        "status": str(status),
        "match_date": match_date or None,
        "match_time": match_time or None,
    }



_MODEL = "gemini-2.5-flash"
_DEMO_HTML = pathlib.Path(__file__).parent.parent.parent / "docs" / "demo.html"

# In-memory active league state (session-scoped; resets on container restart).
_active_league: dict = {"id": config.LEAGUE_ID, "name": "FIFA World Cup Qualification UEFA"}

# Canonical league list — mirrors the frontend dropdown and GET /state response.
# Only leagues verified to return fixture data from free-api-live-football-data are included.
_AVAILABLE_LEAGUES: list[dict] = [
    {"id": 10195, "display": "UEFA WC Qualification",  "season": 2024, "primary": True},
    {"id": 77,    "display": "World Cup 2026",          "season": 2026, "primary": True},
    {"id": 47,    "display": "Premier League",          "season": 2024, "primary": True},
    {"id": 42,    "display": "Champions League",        "season": 2024, "primary": True},
    {"id": 140,   "display": "La Liga",                 "season": 2024, "primary": True},
    {"id": 54,    "display": "Bundesliga",              "season": 2024, "primary": False},
    {"id": 135,   "display": "Serie A",                 "season": 2024, "primary": False},
    {"id": 61,    "display": "Ligue 1",                 "season": 2024, "primary": False},
    {"id": 253,   "display": "MLS",                     "season": 2025, "primary": False},
    {"id": 71,    "display": "Brasileirao",             "season": 2025, "primary": False},
    {"id": 108,   "display": "Scottish Prem",           "season": 2024, "primary": False},
]

_KNOWN_LEAGUES_FOR_ACTIONS: dict[str, str] = {
    "premier league": "Premier League",
    "epl": "Premier League",
    "champions league": "Champions League",
    "ucl": "Champions League",
    "la liga": "La Liga",
    "bundesliga": "Bundesliga",
    "serie a": "Serie A",
    "ligue 1": "Ligue 1",
    "world cup 2026": "World Cup 2026",
    "world cup": "World Cup 2026",
    "qualification": "UEFA WC Qualification",
    "wc qualification": "UEFA WC Qualification",
}


_REPORT_NAME_STRIP = {
    "generate", "create", "make", "show", "download", "get", "build", "produce",
    "view", "display", "give", "fetch", "find", "pull", "save", "export", "me",
    "a", "an", "the", "please",
}
_REPORT_NAME_STOPWORDS = {
    "a", "an", "the", "any", "all", "report", "scouting", "pdf",
    "me", "for", "about", "please", "of", "on",
}


def _extract_player_name_from_report_q(question: str) -> str:
    """Extract player name from a report request question.

    Handles many phrasings (case-insensitive):
        "Generate Bellingham's scouting report" -> "Bellingham"
        "generate messi's report"               -> "messi"
        "show me messi report"                  -> "messi"
        "download mbappe scouting report"       -> "mbappe"
        "generate report for messi"             -> "messi"
        "create a scouting report about Bellingham" -> "Bellingham"
        "messi report"                          -> "messi"
    """
    # 1. "for/about <Name>"
    for prep in ("for", "about"):
        m = re.search(
            rf"\b{prep}\b\s+([A-Za-z][a-zA-Z]+(?:\s+[A-Za-z][a-zA-Z]+){{0,2}})",
            question,
            re.IGNORECASE,
        )
        if m:
            name = m.group(1).strip()
            if name.lower() not in _REPORT_NAME_STOPWORDS:
                return name

    # 2. "<Name>'s (scouting) report"
    m = re.search(
        r"([A-Za-z][a-zA-Z]+(?:\s+[A-Za-z][a-zA-Z]+){0,2})['’]s\s+(?:scouting\s+)?report",
        question,
        re.IGNORECASE,
    )
    if m:
        words = m.group(1).strip().split()
        while words and words[0].lower() in _REPORT_NAME_STRIP:
            words.pop(0)
        name = " ".join(words)
        if name:
            return name

    # 3. "<Name> (scouting) report" with no possessive (e.g. "messi report",
    #     "download mbappe scouting report", "show me messi report").
    m = re.search(
        r"([A-Za-z][a-zA-Z]+(?:\s+[A-Za-z][a-zA-Z]+){0,2})\s+(?:scouting\s+)?report\b",
        question,
        re.IGNORECASE,
    )
    if m:
        words = m.group(1).strip().split()
        while words and words[0].lower() in _REPORT_NAME_STRIP:
            words.pop(0)
        # Strip trailing "scouting" — greedy match can absorb it as a name word
        while words and words[-1].lower() in {"scouting", "report"}:
            words.pop()
        name = " ".join(words)
        if name and name.lower() not in _REPORT_NAME_STOPWORDS:
            return name

    return ""


def _infer_page_actions(question: str, answer: str) -> list[dict]:
    actions: list[dict] = []
    q = question.lower()
    a = answer.lower()
    combined = q + " " + a

    switch_q = any(
        w in q
        for w in ("switch", "change league", "change to", "go to", "swap to", "move to", "use premier", "use champions", "use la liga", "use bundesliga")
    )
    switched_a = any(
        w in a
        for w in ("switched to", "switching to", "now active", "league switched", "active league is now", "successfully switched")
    )

    if switch_q or switched_a:
        matched_league = None
        for key, display in _KNOWN_LEAGUES_FOR_ACTIONS.items():
            if key in combined:
                matched_league = display
                break
        # update_league_selector MUST come first so _activeLeagueId is correct
        # when the subsequent reload actions read it.
        if matched_league:
            actions.append({"action": "update_league_selector", "value": matched_league})
        actions += [
            {"action": "reload_teams"},
            {"action": "reload_charts"},
            {"action": "reload_matches"},
        ]
        actions.append({"action": "show_toast", "message": "✓ League switched — data refreshed!", "type": "success"})

    elif any(w in q for w in ("refresh", "sync", "update data", "get latest", "pull latest")):
        actions += [
            {"action": "reload_teams"},
            {"action": "reload_charts"},
            {"action": "reload_matches"},
            {"action": "show_toast", "message": "✓ Data refreshed!", "type": "success"},
        ]

    chart_q = any(w in q for w in ("chart", "graph", "visuali", "plot"))
    if chart_q and any(w in q for w in ("create", "make", "show", "generate", "build")):
        actions.append({"action": "navigate_to_section", "section": "charts"})
        chart_text = re.sub(
            r"^(create|make|generate|build|show)\s+(a\s+|me\s+a\s+|me\s+)?chart\s+(of\s+|showing\s+|for\s+)?",
            "",
            q,
        ).strip() or question
        actions.append({"action": "fill_chart_input", "text": chart_text})

    # Report detection: "download/export/save/pdf" → PDF download flow;
    # "generate/show/create/make" → scout card preview in chat
    is_report_q = any(w in q for w in ("report", "scouting report"))
    is_download_report = is_report_q and any(w in q for w in ("download", "export", "save", "pdf"))
    is_preview_report = is_report_q and any(w in q for w in ("generate", "show", "create", "make")) and not is_download_report
    if is_download_report:
        player_name = _extract_player_name_from_report_q(question)
        actions.append({"action": "navigate_to_section", "section": "reports"})
        if player_name:
            actions.append({"action": "fill_report_input", "player_name": player_name})
            actions.append({"action": "trigger_report_generate"})
    elif is_preview_report:
        player_name = _extract_player_name_from_report_q(question)
        if player_name:
            actions.append({"action": "show_scout_card", "player_name": player_name})
        else:
            actions.append({"action": "navigate_to_section", "section": "player-report"})
    elif is_report_q and any(w in a for w in ("assessment", "report", "position", "nationality", "age")):
        actions.append({"action": "navigate_to_section", "section": "reports"})

    # Leaderboard / top performers detection
    _no_chart_or_switch = "chart" not in q and "switch" not in q
    is_leaderboard_q = (
        any(w in q for w in (
            "top scorer", "top assist", "top perform", "leaderboard",
            "most goals", "most assists", "highest rated", "best rating",
            "top goal", "leading scorer",
        )) and _no_chart_or_switch
    ) or (
        any(w in q for w in ("top", "best", "most", "highest", "leading", "based on")) and
        any(w in q for w in ("goals", "assists", "scoring", "rating")) and
        _no_chart_or_switch
    )
    if is_leaderboard_q:
        if any(w in q for w in ("assist", "assists")):
            lb_stat = "assists"
        elif any(w in q for w in ("rating", "rated")):
            lb_stat = "rating"
        else:
            lb_stat = "goals"
        actions.append({"action": "navigate_to_section", "section": "top-performers"})
        actions.append({"action": "switch_leaderboard_tab", "stat": lb_stat})

    return actions


app = FastAPI(title="Scout WC26", description="AI scouting agent for the 2026 FIFA World Cup")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def serve_demo() -> FileResponse:
    return FileResponse(
        _DEMO_HTML,
        media_type="text/html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": _MODEL, "dataset": config.BQ_DATASET}


def _loaded_league_ids() -> set[int]:
    """Return league IDs that already have player data in BigQuery.

    Used by /state to flag pre-loaded leagues (green dot in the dropdown) and
    by /admin/switch-league to skip the 60s ingest when data is already present.
    Returns an empty set on any error so callers fall back to the slow path.
    """
    table = config.table("gold_player_stats")
    try:
        rows = bq.run_query(
            "SELECT DISTINCT league_id FROM `" + table + "` WHERE league_id IS NOT NULL"
        )
    except Exception as exc:
        logger.warning("_loaded_league_ids query failed: %s", exc)
        return set()
    out: set[int] = set()
    for r in rows:
        try:
            out.add(int(r["league_id"]))
        except (TypeError, ValueError, KeyError):
            continue
    return out


@app.get("/state")
def get_state() -> dict:
    """Single source of truth for frontend state — active league and available leagues."""
    active_id = _active_league["id"]
    display = next(
        (lg["display"] for lg in _AVAILABLE_LEAGUES if lg["id"] == active_id),
        _active_league.get("name", ""),
    )
    loaded = _loaded_league_ids()
    leagues_with_status = [
        {**lg, "loaded": lg["id"] in loaded} for lg in _AVAILABLE_LEAGUES
    ]
    return {
        "active_league": {"id": active_id, "display": display},
        "available_leagues": leagues_with_status,
        "loaded_leagues": sorted(loaded),
    }


@app.get("/progress/current")
def progress_current() -> dict:
    from src.utils.progress import get_current_progress

    return get_current_progress()


@app.get("/stream/progress")
async def legacy_progress_redirect():
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/progress/current", status_code=307)


_REFRESH_INTENT_PATTERN = re.compile(
    r"\b(refresh|re[- ]?sync|sync\s+(?:the\s+)?(?:data|scout(?:ing)?))\b",
    re.IGNORECASE,
)


def _is_refresh_intent(question: str) -> bool:
    """Detect 'refresh / sync scouting data' phrasing.

    Refresh is a 2–3 minute Fivetran+pipeline operation. Running it inside the
    /query handler causes Cloud Run to drop the connection with 503. Intercept
    the request here, dispatch the same background thread that POST /refresh
    uses, and return a canned answer immediately.
    """
    if not question:
        return False
    if "switch" in question.lower():
        return False
    return bool(_REFRESH_INTENT_PATTERN.search(question))


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    from src.utils.progress import reset_progress

    logger.info("POST /query: question=%r", request.question)
    reset_progress()

    if _is_refresh_intent(request.question):
        logger.info("POST /query: refresh intent detected — dispatching background thread")
        threading.Thread(target=agent_tools.refresh_scouting_data, daemon=True).start()
        answer = (
            "🔄 Scouting data refresh started — watch the progress panel above. "
            "Teams, charts, and matches will reload automatically when the sync completes."
        )
        page_actions = _infer_page_actions(request.question, answer)
        return QueryResponse(answer=answer, question=request.question, page_actions=page_actions)

    answer = scout_agent.run_query(request.question)
    page_actions = _infer_page_actions(request.question, answer)
    return QueryResponse(answer=answer, question=request.question, page_actions=page_actions)


@app.post("/adk/query", response_model=QueryResponse)
async def adk_query(request: QueryRequest) -> QueryResponse:
    """Run the question through the Google ADK agent (Agent Builder integration)."""
    from google.adk.runners import InMemoryRunner
    from google.genai import types
    from scout_adk.agent import root_agent

    logger.info("POST /adk/query: question=%r", request.question)

    _APP = "scout"
    runner = InMemoryRunner(agent=root_agent, app_name=_APP)
    session = await runner.session_service.create_session(app_name=_APP, user_id="api")

    final_text = ""
    async for event in runner.run_async(
        user_id="api",
        session_id=session.id,
        new_message=types.Content(
            role="user", parts=[types.Part(text=request.question)]
        ),
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(p.text or "" for p in event.content.parts)

    return QueryResponse(answer=final_text, question=request.question)


@app.get("/charts/squad-age-profile")
def chart_squad_age_profile(league_id: Optional[int] = None) -> dict:
    # When no league_id is passed, default to the active league but fall back
    # to all leagues if the active league has no data yet (e.g. fresh deploy).
    explicit = league_id is not None
    lid = str(league_id) if league_id else str(_active_league["id"])
    base_sql = (
        "SELECT team_name, ROUND(AVG(age), 1) as avg_age "
        "FROM `" + config.table("gold_player_stats") + "` "
        "WHERE age IS NOT NULL"
    )
    rows = bq.run_query(
        base_sql + " AND league_id = '" + _esc(lid) + "' "
        "GROUP BY team_name ORDER BY avg_age ASC LIMIT 10"
    )
    if not rows and not explicit:
        rows = bq.run_query(base_sql + " GROUP BY team_name ORDER BY avg_age ASC LIMIT 10")
    return {
        "labels": [r["team_name"] for r in rows],
        "data": [float(r["avg_age"]) for r in rows],
        "title": "Youngest Squads (Avg Age)",
    }


@app.get("/charts/top-teams")
def chart_top_teams(league_id: Optional[int] = None) -> dict:
    explicit = league_id is not None
    lid = str(league_id) if league_id else str(_active_league["id"])
    table = config.table("gold_team_summary")
    rows = bq.run_query(
        "SELECT team_name, points FROM `" + table + "` "
        "WHERE league_id = '" + _esc(lid) + "' "
        "ORDER BY points DESC LIMIT 15"
    )
    if not rows and not explicit:
        rows = bq.run_query(
            "SELECT team_name, points FROM `" + table + "` ORDER BY points DESC LIMIT 15"
        )
    return {
        "labels": [r["team_name"] for r in rows],
        "data": [r["points"] for r in rows],
        "title": "Top 15 Teams by Points",
    }


@app.get("/charts/team-depth/{team_name}")
def chart_team_depth(team_name: str, league_id: Optional[int] = None) -> dict:
    _POS_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3, "UNKNOWN": 4}
    explicit = league_id is not None
    lid = str(league_id) if league_id else str(_active_league["id"])
    table = config.table("gold_player_stats")
    base = (
        "SELECT position, COUNT(*) as cnt FROM `" + table + "` "
        "WHERE " + unaccent_sql("team_name") + " LIKE '%" + _esc(unaccent(team_name)) + "%'"
    )
    rows = bq.run_query(base + " AND league_id = '" + _esc(lid) + "' GROUP BY position")
    if not rows and not explicit:
        rows = bq.run_query(base + " GROUP BY position")
    rows.sort(key=lambda r: _POS_ORDER.get(r.get("position", ""), 99))
    return {
        "labels": [r["position"] for r in rows],
        "data": [r["cnt"] for r in rows],
        "title": f"Position Depth — {team_name.title()}",
    }


@app.post("/charts/ai-generate")
def chart_ai_generate(body: ChartRequest) -> dict:
    import json

    import google.genai as genai
    from google.genai import types

    table_ps = config.table("gold_player_stats")
    table_ts = config.table("gold_team_summary")
    table_mr = config.table("gold_match_results")
    table_tp = config.table("gold_top_performers")

    client = genai.Client(vertexai=True, project=config.PROJECT_ID, location=config.REGION)

    plan_prompt = (
        f'You are a data visualization expert building charts from BigQuery.\n\n'
        f'User wants to see: "{body.request}"\n\n'
        f"You have access to these BigQuery tables. Generate a SQL SELECT query using ONLY these tables and columns:\n\n"
        f"gold_player_stats columns (full ID: `{table_ps}`):\n"
        f"  player_id, name, team_name, position (GK/DEF/MID/FWD/UNKNOWN),\n"
        f"  nationality, age, jersey_number, league_id\n\n"
        f"gold_team_summary columns (full ID: `{table_ts}`):\n"
        f"  team_name, matches_played, wins, draws, losses,\n"
        f"  goals_for, goals_against, goal_difference, points\n\n"
        f"gold_match_results columns (full ID: `{table_mr}`):\n"
        f"  fixture_id, home_team_name, away_team_name,\n"
        f"  home_score, away_score, match_date, winner,\n"
        f"  goal_difference, total_goals\n\n"
        f"gold_top_performers columns (full ID: `{table_tp}`):\n"
        f"  player_name, team_name, goals (INT, nullable), assists (INT, nullable),\n"
        f"  rating (FLOAT, nullable), stat_type ('goals'|'assists'|'rating'), rank\n\n"
        f"IMPORTANT RULES:\n"
        f"- Only use SELECT queries\n"
        f"- Use LIMIT 20 maximum\n"
        f"- Return exactly 2 columns: a string label column first, a numeric value column second\n"
        f"- For top scorers, goal leaders, or assist leaders use gold_top_performers "
        f"  filtered by stat_type = 'goals' or 'assists' — this data IS available\n"
        f"- For per-match player goals (not in any table) — set sql to null and explain in error\n"
        f"- For match results and team scores, use gold_match_results\n"
        f"- For player profiles and squad data, use gold_player_stats\n"
        f"- For league standings, use gold_team_summary\n"
        f"- Table references must use the full IDs provided above\n\n"
        f"Return JSON with exactly these keys (raw JSON, no markdown):\n"
        f'{{"sql": "SELECT ...", "chart_type": "bar|line|doughnut", "title": "descriptive title", "error": null}}\n\n'
        f"If the request cannot be answered with available data, return:\n"
        f'{{"sql": null, "chart_type": null, "title": null, "error": "explanation of why"}}'
    )

    plan_resp = client.models.generate_content(
        model=_MODEL,
        contents=plan_prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    try:
        plan = json.loads(plan_resp.text or "{}")
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=500, detail="Gemini returned an unparseable chart plan")

    if plan.get("error"):
        raise HTTPException(status_code=422, detail=plan["error"])

    sql = (plan.get("sql") or "").strip()
    chart_type = plan.get("chart_type", "bar")
    title = plan.get("title") or body.request

    if not sql.upper().lstrip().startswith("SELECT"):
        raise HTTPException(status_code=400, detail="Gemini did not produce a SELECT query")
    if chart_type not in ("bar", "line", "doughnut"):
        chart_type = "bar"

    try:
        rows = bq.run_query(sql)
    except Exception as exc:
        logger.error("AI chart query failed: sql=%s err=%s", sql, exc)
        raise HTTPException(status_code=422, detail=f"Query execution failed: {exc}")

    if not rows:
        return {"labels": [], "data": [], "chart_type": chart_type, "title": title}

    keys = list(rows[0].keys())
    label_key = keys[0]
    value_key = keys[1] if len(keys) > 1 else keys[0]
    labels = [str(r.get(label_key, "")) for r in rows]
    data: list[float] = []
    for r in rows:
        v = r.get(value_key, 0)
        try:
            data.append(float(v))
        except (TypeError, ValueError):
            data.append(0.0)

    return {"labels": labels, "data": data, "chart_type": chart_type, "title": title}


@app.get("/leaderboard")
def leaderboard(
    stat: str = "goals",
    limit: int = 10,
    league_id: Optional[int] = None,
    all_leagues: bool = False,
) -> dict:
    """Return top performers ranked by goals, assists, or rating.

    `gold_top_performers` currently has no league_id column so the league_id
    and all_leagues params are passthrough — the underlying data already spans
    every loaded league. Reserved for when per-league filtering is added.
    """
    valid = {"goals", "assists", "rating"}
    if stat not in valid:
        stat = "goals"
    safe_limit = min(max(1, int(limit)), 50)
    table = config.table("gold_top_performers")
    sql = (
        "SELECT player_name, team_name, "
        + stat
        + ", rank FROM `"
        + table
        + "` WHERE stat_type = '"
        + _esc(stat)
        + "' AND "
        + stat
        + " IS NOT NULL ORDER BY rank ASC LIMIT "
        + str(safe_limit)
    )
    try:
        rows = bq.run_query(sql)
    except Exception as exc:
        logger.warning("Leaderboard query failed: %s", exc)
        rows = []
    return {
        "players": rows,
        "stat": stat,
        "league": _active_league.get("name", ""),
        "all_leagues": all_leagues,
    }


@app.get("/charts/top-scorers")
def chart_top_scorers() -> dict:
    table = config.table("gold_top_performers")
    sql = (
        "SELECT player_name, goals FROM `"
        + table
        + "` WHERE stat_type = 'goals' AND goals IS NOT NULL "
        "ORDER BY rank ASC LIMIT 10"
    )
    try:
        rows = bq.run_query(sql)
    except Exception as exc:
        logger.warning("Top scorers chart query failed: %s", exc)
        rows = []
    league_name = _active_league.get("name", "")
    return {
        "labels": [r["player_name"] for r in rows],
        "data": [r["goals"] for r in rows],
        "title": f"Top Scorers — {league_name}",
    }


_LEAGUE_NAME_BY_ID: dict[str, str] = {str(lg["id"]): lg["display"] for lg in _AVAILABLE_LEAGUES}


def _row_to_match(row: dict, *, is_completed: bool) -> dict:
    league_id = str(row.get("league_id", ""))
    return {
        "fixture_id": row.get("fixture_id"),
        "home_team": row.get("home_team_name", ""),
        "away_team": row.get("away_team_name", ""),
        "home_score": row.get("home_score"),
        "away_score": row.get("away_score"),
        "status": row.get("status", "") or ("FT" if is_completed else "NS"),
        "match_date": row.get("match_date"),
        "match_time": None,
        "league_id": league_id,
        "league_name": _LEAGUE_NAME_BY_ID.get(league_id, f"League {league_id}"),
        "is_completed": is_completed,
    }


# Football API status codes that mean a match is currently in play.
# 1H/2H = halves, HT = half-time break, ET = extra time, BT = break time,
# P = penalty shootout. "LIVE" is a generic fallback some feeds use.
_LIVE_STATUSES = ("1H", "2H", "HT", "ET", "BT", "P", "LIVE")
_MATCH_BUCKET_LIMIT = 5


@app.get("/matches/live-upcoming")
def matches_live_upcoming(league_id: Optional[int] = None) -> dict:
    """Return matches split into three buckets: live, upcoming, recent.

    - live:     in-play matches (status 1H/2H/HT/ET/BT/P/LIVE) — no cap
    - upcoming: not-yet-started fixtures (status NS, date >= today), max 5
    - recent:   completed matches, deduplicated to 1 per league, max 5

    Falls back to the most-recent completed matches when no upcoming fixtures
    exist so the demo dashboard is always populated. Pass ?league_id=X to
    restrict to a single league.
    """
    table = config.table("silver_fixtures")
    league_clause = ""
    if league_id is not None:
        league_clause = " AND league_id = '" + _esc(str(int(league_id))) + "'"

    live_in = ", ".join("'" + s + "'" for s in _LIVE_STATUSES)
    live_sql = (
        "SELECT fixture_id, home_team_name, away_team_name, "
        "home_score, away_score, status, "
        "CAST(match_date AS STRING) AS match_date, league_id "
        "FROM `" + table + "` "
        "WHERE is_completed = FALSE AND UPPER(status) IN (" + live_in + ")"
        + league_clause + " "
        "ORDER BY match_date ASC LIMIT 20"
    )
    try:
        live_rows = bq.run_query(live_sql)
    except Exception as exc:
        logger.warning("Live matches query failed: %s", exc)
        live_rows = []
    live = [_row_to_match(r, is_completed=False) for r in live_rows]

    upcoming_sql = (
        "SELECT fixture_id, home_team_name, away_team_name, "
        "home_score, away_score, status, "
        "CAST(match_date AS STRING) AS match_date, league_id "
        "FROM `" + table + "` "
        "WHERE match_date >= CURRENT_DATE() "
        "AND is_completed = FALSE "
        "AND UPPER(status) NOT IN (" + live_in + ")"
        + league_clause + " "
        "ORDER BY match_date ASC LIMIT 20"
    )
    try:
        upcoming_rows = bq.run_query(upcoming_sql)
    except Exception as exc:
        logger.warning("Upcoming matches query failed: %s", exc)
        upcoming_rows = []
    upcoming = [_row_to_match(r, is_completed=False) for r in upcoming_rows]
    upcoming = upcoming[:_MATCH_BUCKET_LIMIT]

    # Pull a wider pool then dedupe to 1 per league so the panel doesn't get
    # dominated by a single league's results.
    recent_sql = (
        "SELECT fixture_id, home_team_name, away_team_name, "
        "home_score, away_score, status, "
        "CAST(match_date AS STRING) AS match_date, league_id "
        "FROM `" + table + "` "
        "WHERE is_completed = TRUE" + league_clause + " "
        "ORDER BY match_date DESC LIMIT 40"
    )
    try:
        recent_rows = bq.run_query(recent_sql)
    except Exception as exc:
        logger.warning("Recent matches query failed: %s", exc)
        recent_rows = []

    seen_leagues: set[str] = set()
    deduped_recent: list[dict] = []
    for r in recent_rows:
        lid = str(r.get("league_id", ""))
        if lid in seen_leagues:
            continue
        seen_leagues.add(lid)
        deduped_recent.append(_row_to_match(r, is_completed=True))
        if len(deduped_recent) >= _MATCH_BUCKET_LIMIT:
            break

    if not live and not upcoming and not deduped_recent:
        return {
            "live": [],
            "upcoming": [],
            "recent": [],
            "message": "World Cup 2026 begins June 11",
        }

    return {"live": live, "upcoming": upcoming, "recent": deduped_recent}


@app.get("/matches/score/{fixture_id}")
def matches_score(fixture_id: str) -> dict:
    """Return detailed match info for a single fixture — used by clickable cards.

    Pulls from silver_fixtures (basic match data) and joins with
    gold_match_results when the match is completed (for winner + total_goals).
    """
    table = config.table("silver_fixtures")
    sql = (
        "SELECT fixture_id, home_team_name, away_team_name, "
        "home_score, away_score, status, "
        "CAST(match_date AS STRING) AS match_date, league_id, is_completed "
        "FROM `" + table + "` "
        "WHERE fixture_id = '" + _esc(fixture_id) + "' LIMIT 1"
    )
    try:
        rows = bq.run_query(sql)
    except Exception as exc:
        logger.warning("Match score query failed: %s", exc)
        rows = []
    if not rows:
        raise HTTPException(status_code=404, detail=f"Fixture '{fixture_id}' not found")
    row = rows[0]
    league_id = str(row.get("league_id", ""))
    is_completed = bool(row.get("is_completed"))
    result: dict = {
        "fixture_id": row.get("fixture_id"),
        "home_team": row.get("home_team_name", ""),
        "away_team": row.get("away_team_name", ""),
        "home_score": row.get("home_score"),
        "away_score": row.get("away_score"),
        "status": row.get("status", "") or ("FT" if is_completed else "NS"),
        "match_date": row.get("match_date"),
        "league_id": league_id,
        "league_name": _LEAGUE_NAME_BY_ID.get(league_id, f"League {league_id}"),
        "is_completed": is_completed,
        "winner": None,
        "total_goals": None,
        "goal_difference": None,
    }
    if is_completed:
        gold = config.table("gold_match_results")
        try:
            gsql = (
                "SELECT winner, total_goals, goal_difference "
                "FROM `" + gold + "` "
                "WHERE fixture_id = '" + _esc(fixture_id) + "' LIMIT 1"
            )
            grows = bq.run_query(gsql)
            if grows:
                gr = grows[0]
                result["winner"] = gr.get("winner")
                result["total_goals"] = gr.get("total_goals")
                result["goal_difference"] = gr.get("goal_difference")
        except Exception as exc:
            logger.warning("gold_match_results lookup failed: %s", exc)
    return result


@app.post("/report/pdf/{player_name}")
def report_pdf(player_name: str) -> Response:
    from datetime import date
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        HRFlowable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    logger.info("POST /report/pdf/%s", player_name)

    player = agent_tools.get_player_detail(player_name=player_name)
    _words = player_name.strip().split()
    if not player and len(_words) > 1:
        # Strip leading action word (handles stale "Generate Bellingham" → "Bellingham")
        player = agent_tools.get_player_detail(player_name=" ".join(_words[1:]))
    if not player and len(_words) > 2:
        player = agent_tools.get_player_detail(player_name=_words[-1])
    if not player:
        # Last resort: search across ALL leagues (handles requests while a different league is active)
        _names_to_try = [player_name]
        if len(_words) > 1:
            _names_to_try.append(" ".join(_words[1:]))
        if len(_words) > 2:
            _names_to_try.append(_words[-1])
        for _n in _names_to_try:
            _sql = (
                "SELECT * FROM `" + config.table("gold_player_stats") + "` "
                "WHERE " + unaccent_sql("name") + " LIKE '%" + _esc(unaccent(_n)) + "%' LIMIT 1"
            )
            _rows = bq.run_query(_sql)
            if _rows:
                player = _rows[0]
                break
    if not player:
        # Last shot: ask Gemini which league this player is in and surface a
        # structured 422 so the frontend can prompt the user to switch instead
        # of throwing a bare "not found" toast.
        try:
            import google.genai as _g
            from google.genai import types as _gt
            _c = _g.Client(vertexai=True, project=config.PROJECT_ID, location=config.REGION)
            _p = (
                f"Which professional football league does {player_name} currently play in? "
                'Reply JSON: {"club": "...", "league": "...", "known": true|false}. '
                "League MUST be one of: MLS, La Liga, Premier League, Champions League, "
                "Bundesliga, Serie A, Ligue 1, Brasileirao, UEFA WC Qualification, "
                "Saudi Pro League, Other."
            )
            _r = _c.models.generate_content(
                model=_MODEL,
                contents=_p,
                config=_gt.GenerateContentConfig(response_mime_type="application/json"),
            )
            import json as _json
            _s = _json.loads(_r.text or "{}")
            if _s.get("known"):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "status": "not_loaded",
                        "player_name": player_name,
                        "club": _s.get("club", ""),
                        "suggested_league": _s.get("league", ""),
                        "message": (
                            f"{player_name} plays for {_s.get('club','')} in "
                            f"{_s.get('league','')}. Switch leagues from the dropdown "
                            "to load that data, then re-generate the PDF."
                        ),
                    },
                )
        except HTTPException:
            raise
        except Exception:
            pass
        raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")

    team_name = player.get("team_name", "")
    team = agent_tools.query_team_summary(team_name=team_name) if team_name else {}
    roster = agent_tools.get_team_roster(team_name=team_name) if team_name else []

    _wins = team.get("wins", 0) if team else 0
    _draws = team.get("draws", 0) if team else 0
    _losses = team.get("losses", 0) if team else 0
    _points = team.get("points", 0) if team else 0
    _matches = team.get("matches_played", 0) if team else 0
    _pname = player.get("name", player_name)
    _age = player.get("age", "unknown")
    _position = player.get("position", "unknown")
    _nationality = player.get("nationality", "unknown")

    # Query top performers stats for this player (supplementary — non-fatal)
    _top_stat_label = ""
    _top_stat_value = ""
    try:
        top_sql = (
            "SELECT stat_type, goals, assists, rating, rank "
            "FROM `" + config.table("gold_top_performers") + "` "
            "WHERE " + unaccent_sql("player_name") + " LIKE '%" + _esc(unaccent(_pname)) + "%' "
            "ORDER BY rank ASC LIMIT 3"
        )
        top_rows = bq.run_query(top_sql)
        if top_rows:
            r = top_rows[0]
            if r.get("stat_type") == "goals" and r.get("goals") is not None:
                _top_stat_label = "GOALS"
                _top_stat_value = f"{r['goals']} (Rank #{r['rank']})"
            elif r.get("stat_type") == "assists" and r.get("assists") is not None:
                _top_stat_label = "ASSISTS"
                _top_stat_value = f"{r['assists']} (Rank #{r['rank']})"
            elif r.get("stat_type") == "rating" and r.get("rating") is not None:
                _top_stat_label = "RATING"
                _top_stat_value = f"{float(r['rating']):.2f} (Rank #{r['rank']})"
    except Exception:
        pass

    # Direct one-shot Gemini call (no tools, no agent loop) — keeps PDF generation
    # under ~10s. Using the full scout_agent.run_query() here ran the whole 5-round
    # tool loop and took 30–60s for a report that needs no DB lookups (we already
    # have the data in hand).
    import google.genai as genai
    from google.genai import types as genai_types

    _scout_prompt = (
        f"You are a UEFA-licensed football scout. Write a professional 4-5 sentence scouting report for "
        f"{_pname}, {_age} years old, {_position} for {team_name} ({_nationality}).\n\n"
        f"Cover these points in order:\n"
        f"1. Playing style typical for their position and age\n"
        f"2. Their role in the team given {team_name}'s record of {_wins}W {_draws}D {_losses}L\n"
        f"3. Key strengths based on their profile\n"
        f"4. Transfer/recruitment recommendation with a specific tier "
        f"(e.g. 'top 5 league ready', 'strong Championship/second division level', 'promising development prospect')\n\n"
        f"Write 4-5 sentences. Be specific and professional. "
        f"Do not refuse or hedge. Do not say you lack data."
    )
    _genai_client = genai.Client(vertexai=True, project=config.PROJECT_ID, location=config.REGION)
    _scout_resp = _genai_client.models.generate_content(
        model=_MODEL,
        contents=_scout_prompt,
        config=genai_types.GenerateContentConfig(),
    )
    scouting_para = (_scout_resp.text or "").strip() or "No assessment available."

    buffer = BytesIO()
    PAGE_W = letter[0]
    MARGIN = 0.75 * inch
    usable_w = PAGE_W - 2 * MARGIN

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )

    DARK = colors.HexColor("#1a1a2e")
    BLUE = colors.HexColor("#4285F4")
    MUTED = colors.HexColor("#586069")
    LIGHT = colors.HexColor("#f0f2f5")
    BORDER = colors.HexColor("#e1e4e8")
    WHITE = colors.white

    def _style(name, **kw):
        return ParagraphStyle(name, **kw)

    hdr_left_style = _style("hl", fontName="Helvetica-Bold", fontSize=11, textColor=WHITE)
    hdr_right_style = _style("hr2", fontName="Helvetica", fontSize=9, textColor=WHITE, alignment=2)
    name_style = _style("nm", fontName="Helvetica-Bold", fontSize=24, leading=30, spaceAfter=10, textColor=colors.black)
    subtitle_style = _style("sub", fontName="Helvetica", fontSize=14, leading=18, textColor=MUTED, spaceAfter=14)
    section_style = _style("sec", fontName="Helvetica-Bold", fontSize=11, textColor=colors.black, spaceBefore=14, spaceAfter=4)
    body_style = _style("bd", fontName="Helvetica", fontSize=11, leading=16, spaceAfter=4)
    assess_style = _style("assess", fontName="Helvetica", fontSize=11, leading=17, leftIndent=4, rightIndent=4)
    footer_white_style = _style("fw", fontName="Helvetica", fontSize=9, textColor=WHITE, alignment=1)

    story = []

    # Thin blue accent bar at very top of page
    accent_tbl = Table([[""]], colWidths=[usable_w])
    accent_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BLUE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(accent_tbl)
    story.append(Spacer(1, 0.06 * inch))

    # Dark header bar: "SCOUT WC26" left, date right
    today_str = date.today().strftime("%d %b %Y")
    hdr_data = [[Paragraph("SCOUT WC26", hdr_left_style), Paragraph(today_str, hdr_right_style)]]
    hdr_tbl = Table(hdr_data, colWidths=[usable_w * 0.6, usable_w * 0.4])
    hdr_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (0, -1), 12),
        ("RIGHTPADDING", (-1, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(hdr_tbl)
    story.append(Spacer(1, 0.18 * inch))

    # Player name (24pt bold) + position · team subtitle (14pt gray)
    story.append(Paragraph(_pname, name_style))
    story.append(Paragraph(f"{_position} · {team_name}", subtitle_style))

    # Horizontal rule in blue
    story.append(HRFlowable(width="100%", thickness=2, color=BLUE, spaceAfter=10))

    # Key stats in 2-column layout (4 table columns: label, value, label, value)
    cw = usable_w / 4
    stats_data = [
        ["POSITION", player.get("position", "—"), "TEAM", team_name or "—"],
        ["AGE", str(player.get("age", "—")), "MATCHES", str(_matches)],
        ["NATIONALITY", player.get("nationality", "—"), "RECORD", f"{_wins}W {_draws}D {_losses}L"],
        ["JERSEY #", str(player.get("jersey_number", "—")), "POINTS", str(_points)],
    ]
    if _top_stat_label:
        stats_data.append([_top_stat_label, _top_stat_value, "", ""])
    stats_tbl = Table(stats_data, colWidths=[cw * 0.75, cw * 1.25, cw * 0.75, cw * 1.25])
    stats_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTNAME", (3, 0), (3, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (0, -1), MUTED),
        ("TEXTCOLOR", (2, 0), (2, -1), MUTED),
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT, WHITE]),
        ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("LINEAFTER", (1, 0), (1, -1), 1.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(stats_tbl)
    story.append(Spacer(1, 0.15 * inch))

    # Squad roster in 4 columns: GK | DEF | MID | FWD
    story.append(Paragraph("SQUAD ROSTER", section_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=BLUE, spaceAfter=8))

    if roster:
        pos_groups: dict[str, list[str]] = {}
        for p in roster:
            pos = p.get("position", "UNKNOWN")
            pos_groups.setdefault(pos, []).append(p.get("name", ""))
        gk = pos_groups.get("GK", [])
        def_players = pos_groups.get("DEF", [])
        mid_players = pos_groups.get("MID", [])
        fwd = pos_groups.get("FWD", [])
        max_rows = max(len(gk), len(def_players), len(mid_players), len(fwd), 1)
        roster_data = [["GK", "DEF", "MID", "FWD"]]
        for i in range(max_rows):
            roster_data.append([
                gk[i] if i < len(gk) else "",
                def_players[i] if i < len(def_players) else "",
                mid_players[i] if i < len(mid_players) else "",
                fwd[i] if i < len(fwd) else "",
            ])
        cw4 = usable_w / 4
        roster_tbl = Table(roster_data, colWidths=[cw4] * 4)
        roster_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), DARK),
            ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT, WHITE]),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(roster_tbl)
    else:
        story.append(Paragraph("No roster data available.", body_style))

    story.append(Spacer(1, 0.15 * inch))

    # Scouting assessment in indented box with light gray background
    story.append(Paragraph("SCOUTING ASSESSMENT", section_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=BLUE, spaceAfter=8))

    assess_data = [[Paragraph(scouting_para or "No assessment available.", assess_style)]]
    assess_tbl = Table(assess_data, colWidths=[usable_w])
    assess_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(assess_tbl)
    story.append(Spacer(1, 0.3 * inch))

    # Footer bar matching header color
    footer_data = [[Paragraph("Generated by Scout WC26 | Powered by Gemini + BigQuery", footer_white_style)]]
    footer_tbl = Table(footer_data, colWidths=[usable_w])
    footer_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), DARK),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(footer_tbl)

    doc.build(story)
    buffer.seek(0)

    safe_name = _pname.replace(" ", "_")
    return Response(
        content=buffer.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_scouting_report.pdf"'},
    )


@app.post("/report/{player_name}", response_model=ReportResponse)
def report(player_name: str) -> ReportResponse:
    logger.info("POST /report/%s", player_name)
    result = scout_agent.generate_scouting_report(player_name)
    if not result:
        raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")

    # Player isn't in the loaded data but Gemini knew which league they're in.
    # Surface the suggestion to the frontend instead of pretending it's a real report.
    if result.get("status") == "not_loaded":
        return ReportResponse(
            player_name=result.get("player_name", player_name),
            status="not_loaded",
            message=result.get("message", ""),
            suggested_league=result.get("suggested_league", ""),
            club=result.get("club", ""),
        )

    jersey = wins = draws = losses = points = matches = None
    try:
        player = agent_tools.get_player_detail(player_name=player_name)
        if player:
            jersey = player.get("jersey_number")
            team_name = player.get("team_name", "")
            if team_name:
                team = agent_tools.query_team_summary(team_name=team_name)
                if team:
                    wins = team.get("wins")
                    draws = team.get("draws")
                    losses = team.get("losses")
                    points = team.get("points")
                    matches = team.get("matches_played")
    except Exception:
        pass

    return ReportResponse(
        **result,
        jersey=jersey,
        wins=wins,
        draws=draws,
        losses=losses,
        points=points,
        matches=matches,
    )


_WC2026_LEAGUE_ID = 77
_WC2026_KICKOFF = "2026-06-11"
_WC2026_COMING_SOON_MSG = (
    "FIFA World Cup 2026 begins June 11, 2026. Squad and match data will "
    "appear here automatically once the tournament begins."
)


_POSITION_ORDER = {"GK": 1, "DEF": 2, "MID": 3, "FWD": 4, "UNKNOWN": 5}


@app.get("/teams/{team_name}/detail")
def team_detail(team_name: str) -> dict:
    """Return full squad + summary for a single team across all leagues.

    Used by the clickable team-card drill-down in the demo UI. Searches
    accent-folded so 'Garcia' matches 'García', etc. Returns a derived
    formation string (e.g. "1-4-3-3") computed from position counts.
    """
    logger.info("GET /teams/%s/detail", team_name)
    players_tbl = config.table("gold_player_stats")
    teams_tbl = config.table("gold_team_summary")
    folded = _esc(unaccent(team_name))

    # Pull players from every league — drill-down should work for any team the
    # user clicked, regardless of which league is active now.
    players_sql = (
        "SELECT name, position, age, jersey_number, nationality, "
        "team_name, league_id "
        "FROM `" + players_tbl + "` "
        "WHERE " + unaccent_sql("team_name") + " LIKE '%" + folded + "%' "
        "ORDER BY "
        " CASE position "
        "   WHEN 'GK' THEN 1 WHEN 'DEF' THEN 2 "
        "   WHEN 'MID' THEN 3 WHEN 'FWD' THEN 4 ELSE 5 END, "
        " name"
    )
    try:
        players = bq.run_query(players_sql)
    except Exception as exc:
        logger.warning("team_detail player query failed: %s", exc)
        players = []

    summary_sql = (
        "SELECT team_name, matches_played, wins, draws, losses, "
        "goals_for, goals_against, goal_difference, points, league_id "
        "FROM `" + teams_tbl + "` "
        "WHERE " + unaccent_sql("team_name") + " LIKE '%" + folded + "%' "
        "ORDER BY points DESC LIMIT 1"
    )
    try:
        srows = bq.run_query(summary_sql)
        summary = srows[0] if srows else {}
    except Exception as exc:
        logger.warning("team_detail summary query failed: %s", exc)
        summary = {}

    pos_counts: dict[str, int] = {}
    for p in players:
        pos = p.get("position") or "UNKNOWN"
        pos_counts[pos] = pos_counts.get(pos, 0) + 1
    n_def = pos_counts.get("DEF", 0)
    n_mid = pos_counts.get("MID", 0)
    n_fwd = pos_counts.get("FWD", 0)
    formation = f"1-{n_def}-{n_mid}-{n_fwd}" if (n_def or n_mid or n_fwd) else "—"

    canonical_name = players[0].get("team_name") if players else (
        summary.get("team_name") if summary else team_name
    )
    league_id = (summary.get("league_id") if summary else (
        players[0].get("league_id") if players else None
    ))

    return {
        "team_name": canonical_name or team_name,
        "league_id": league_id,
        "league_name": _LEAGUE_NAME_BY_ID.get(str(league_id), ""),
        "formation": formation,
        "total_players": len(players),
        "position_counts": pos_counts,
        "summary": summary,
        "squad": players,
    }


@app.get("/teams", response_model=TeamListResponse)
def teams(league_id: Optional[int] = None) -> TeamListResponse:
    logger.info("GET /teams: league_id=%s", league_id)
    table = config.table("gold_team_summary")
    lid = league_id or _active_league.get("id")
    if lid:
        try:
            sql = "SELECT * FROM `" + table + "` WHERE league_id = '" + str(int(lid)) + "' LIMIT 100"
            rows = bq.run_query(sql)
            if rows:
                return TeamListResponse(teams=rows)
        except Exception:
            pass
        # No rows for the requested league. If it's WC2026, signal coming_soon
        # so the frontend can render the qualified-nations placeholder grid
        # instead of falling back to other leagues' data.
        if int(lid) == _WC2026_LEAGUE_ID:
            return TeamListResponse(
                teams=[],
                status="coming_soon",
                message=_WC2026_COMING_SOON_MSG,
                kickoff=_WC2026_KICKOFF,
            )
    sql = "SELECT * FROM `" + table + "` LIMIT 100"
    rows = bq.run_query(sql)
    return TeamListResponse(teams=rows)


@app.post("/refresh")
def refresh() -> dict:
    from src.utils.progress import reset_progress

    logger.info("POST /refresh")
    reset_progress()
    threading.Thread(target=agent_tools.refresh_scouting_data, daemon=True).start()
    return {"status": "started", "message": "Data refresh started in background."}


@app.get("/admin/leagues")
def admin_leagues() -> dict:
    from src.utils.football_api import football_api as _fa

    leagues = _fa.get_available_leagues()
    return {"leagues": leagues, "active": _active_league}


@app.post("/admin/switch-league")
def admin_switch_league(body: SwitchLeagueRequest) -> dict:
    from src.utils.progress import emit_progress, reset_progress
    import src.utils.football_api as _fa_mod

    logger.info("POST /admin/switch-league: id=%d name=%s", body.league_id, body.league_name)
    _active_league["id"] = body.league_id
    _active_league["name"] = body.league_name

    display = next(
        (lg["display"] for lg in _AVAILABLE_LEAGUES if lg["id"] == body.league_id),
        body.league_name,
    )

    reset_progress()

    # Fast path: data already exists for this league — just flip the active
    # pointer, emit a single 'complete' progress step, and skip the 60s ingest.
    if body.league_id in _loaded_league_ids():
        logger.info(
            "POST /admin/switch-league: fast path for id=%d (data already loaded)",
            body.league_id,
        )
        _fa_mod._WORLD_CUP_LEAGUE_ID = body.league_id
        emit_progress(f"✅ Already loaded — switched to {display}", "done", 100)
        return {
            "status": "started",
            "message": f"Switched to '{display}' (data already loaded)",
            "league": {"id": body.league_id, "display": display},
            "ingested": False,
        }

    threading.Thread(
        target=agent_tools.switch_league,
        args=(body.league_name,),
        daemon=True,
    ).start()
    return {
        "status": "started",
        "message": f"Switching to '{display}'...",
        "league": {"id": body.league_id, "display": display},
        "ingested": True,
    }


@app.get("/players", response_model=PlayerListResponse)
def players(
    position: Optional[str] = None,
    team_name: Optional[str] = None,
    nationality: Optional[str] = None,
    league_id: Optional[int] = None,
) -> PlayerListResponse:
    logger.info(
        "GET /players: position=%s team_name=%s nationality=%s league_id=%s",
        position,
        team_name,
        nationality,
        league_id,
    )
    import src.utils.football_api as _fa_mod

    original_lid = _fa_mod._WORLD_CUP_LEAGUE_ID
    if league_id:
        _fa_mod._WORLD_CUP_LEAGUE_ID = league_id
    try:
        rows = agent_tools.query_players(
            position=position,
            team_name=team_name,
            nationality=nationality,
        )
    finally:
        _fa_mod._WORLD_CUP_LEAGUE_ID = original_lid
    rows = rows[:50]
    # Coming-soon signal for WC2026 when no player data exists yet — same
    # contract as /teams so the frontend can show a placeholder.
    effective_lid = league_id or _active_league.get("id")
    if not rows and effective_lid and int(effective_lid) == _WC2026_LEAGUE_ID:
        return PlayerListResponse(
            players=[],
            count=0,
            status="coming_soon",
            message=_WC2026_COMING_SOON_MSG,
            kickoff=_WC2026_KICKOFF,
        )
    return PlayerListResponse(players=rows, count=len(rows))


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
