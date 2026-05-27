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


_REPORT_NAME_STRIP = {"generate", "create", "make", "show", "download", "get", "build", "produce", "view", "display"}


def _extract_player_name_from_report_q(question: str) -> str:
    """Extract player name from a report request question."""
    # "for/about <Name>"
    for prep in ("for", "about"):
        m = re.search(
            rf"\b{prep}\b\s+([A-Za-z][a-zA-Z]+(?:\s+[A-Za-z][a-zA-Z]+){{0,2}})",
            question,
            re.IGNORECASE,
        )
        if m:
            name = m.group(1).strip()
            if name.lower() not in {"a", "an", "the", "any", "all", "report", "scouting", "pdf"}:
                return name
    # "<Name>'s (scouting) report" — greedy match may capture a leading action verb
    # e.g. "Generate Bellingham's scouting report" → captures "Generate Bellingham"
    m = re.search(
        r"([A-Za-z][a-zA-Z]+(?:\s+[A-Za-z][a-zA-Z]+){0,2})'s\s+(?:scouting\s+)?report",
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
        actions += [
            {"action": "reload_teams"},
            {"action": "reload_charts"},
            {"action": "reload_matches"},
        ]
        if matched_league:
            actions.append({"action": "update_league_selector", "value": matched_league})
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

    # Report detection: explicit "generate/download/show report for X" → PDF flow
    is_report_q = any(w in q for w in ("report", "scouting report"))
    is_explicit_report = is_report_q and any(
        w in q for w in ("generate", "download", "create", "make", "get", "show")
    )
    if is_explicit_report:
        player_name = _extract_player_name_from_report_q(question)
        actions.append({"action": "navigate_to_section", "section": "reports"})
        if player_name:
            actions.append({"action": "fill_report_input", "player_name": player_name})
            actions.append({"action": "trigger_report_generate"})
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
def root() -> FileResponse:
    return FileResponse(_DEMO_HTML, media_type="text/html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": _MODEL, "dataset": config.BQ_DATASET}


@app.get("/progress/current")
def progress_current() -> dict:
    from src.utils.progress import get_current_progress

    return get_current_progress()


@app.get("/stream/progress")
async def legacy_progress_redirect():
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/progress/current", status_code=307)


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    from src.utils.progress import reset_progress

    logger.info("POST /query: question=%r", request.question)
    reset_progress()
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
def chart_squad_age_profile() -> dict:
    sql = (
        "SELECT team_name, ROUND(AVG(age), 1) as avg_age "
        "FROM `" + config.table("gold_player_stats") + "` "
        "WHERE age IS NOT NULL "
        "GROUP BY team_name ORDER BY avg_age ASC LIMIT 10"
    )
    rows = bq.run_query(sql)
    return {
        "labels": [r["team_name"] for r in rows],
        "data": [float(r["avg_age"]) for r in rows],
        "title": "Youngest Squads (Avg Age)",
    }


@app.get("/charts/top-teams")
def chart_top_teams() -> dict:
    sql = (
        "SELECT team_name, points "
        "FROM `" + config.table("gold_team_summary") + "` "
        "ORDER BY points DESC LIMIT 15"
    )
    rows = bq.run_query(sql)
    return {
        "labels": [r["team_name"] for r in rows],
        "data": [r["points"] for r in rows],
        "title": "Top 15 Teams by Points",
    }


@app.get("/charts/team-depth/{team_name}")
def chart_team_depth(team_name: str) -> dict:
    _POS_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3, "UNKNOWN": 4}
    sql = (
        "SELECT position, COUNT(*) as cnt "
        "FROM `" + config.table("gold_player_stats") + "` "
        "WHERE LOWER(team_name) LIKE '%" + _esc(team_name.lower()) + "%' "
        "GROUP BY position"
    )
    rows = bq.run_query(sql)
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
def leaderboard(stat: str = "goals", limit: int = 10) -> dict:
    valid = {"goals", "assists", "rating"}
    if stat not in valid:
        stat = "goals"
    safe_limit = min(max(1, int(limit)), 20)
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


@app.get("/matches/live-upcoming")
def matches_live_upcoming() -> dict:
    table = config.table("silver_fixtures")
    sql = (
        "SELECT home_team_name, away_team_name, home_score, away_score, "
        "status, CAST(match_date AS STRING) AS match_date "
        "FROM `" + table + "` "
        "WHERE match_date >= CURRENT_DATE() "
        "AND is_completed = FALSE "
        "ORDER BY match_date ASC LIMIT 10"
    )
    try:
        rows = bq.run_query(sql)
    except Exception as exc:
        logger.warning("Upcoming matches query failed: %s", exc)
        rows = []
    if not rows:
        return {"live": [], "upcoming": [], "message": "World Cup 2026 begins June 11"}
    upcoming = [
        {
            "home_team": r.get("home_team_name", ""),
            "away_team": r.get("away_team_name", ""),
            "home_score": r.get("home_score"),
            "away_score": r.get("away_score"),
            "status": r.get("status", ""),
            "match_date": r.get("match_date"),
            "match_time": None,
        }
        for r in rows
    ]
    return {"live": [], "upcoming": upcoming}


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
    if not player:
        # Fallback: strip leading words (handles stale "Generate Bellingham" → "Bellingham")
        _words = player_name.strip().split()
        if len(_words) > 1:
            player = agent_tools.get_player_detail(player_name=" ".join(_words[1:]))
        if not player and len(_words) > 2:
            player = agent_tools.get_player_detail(player_name=_words[-1])
    if not player:
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
            "WHERE LOWER(player_name) LIKE '%" + _esc(_pname.lower()) + "%' "
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

    scouting_para = scout_agent.run_query(
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
    name_style = _style("nm", fontName="Helvetica-Bold", fontSize=24, spaceAfter=4, textColor=colors.black)
    subtitle_style = _style("sub", fontName="Helvetica", fontSize=14, textColor=MUTED, spaceAfter=10)
    section_style = _style("sec", fontName="Helvetica-Bold", fontSize=11, textColor=colors.black, spaceBefore=14, spaceAfter=4)
    body_style = _style("bd", fontName="Helvetica", fontSize=11, leading=16, spaceAfter=4)
    assess_style = _style("assess", fontName="Helvetica", fontSize=11, leading=17, leftIndent=4, rightIndent=4)
    footer_white_style = _style("fw", fontName="Helvetica", fontSize=9, textColor=WHITE, alignment=1)

    story = []

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
        ["NATIONALITY", player.get("nationality", "—"), "W / D / L", f"{_wins} / {_draws} / {_losses}"],
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

    # Squad roster in 3 columns: GK | DEF/MID | FWD
    story.append(Paragraph("SQUAD ROSTER", section_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=BLUE, spaceAfter=8))

    if roster:
        pos_groups: dict[str, list[str]] = {}
        for p in roster:
            pos = p.get("position", "UNKNOWN")
            pos_groups.setdefault(pos, []).append(p.get("name", ""))
        gk = pos_groups.get("GK", [])
        mid_def = pos_groups.get("DEF", []) + pos_groups.get("MID", [])
        fwd = pos_groups.get("FWD", [])
        max_rows = max(len(gk), len(mid_def), len(fwd), 1)
        roster_data = [["GK", "DEF / MID", "FWD"]]
        for i in range(max_rows):
            roster_data.append([
                gk[i] if i < len(gk) else "",
                mid_def[i] if i < len(mid_def) else "",
                fwd[i] if i < len(fwd) else "",
            ])
        cw3 = usable_w / 3
        roster_tbl = Table(roster_data, colWidths=[cw3] * 3)
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
    return ReportResponse(**result)


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
    from src.utils.progress import reset_progress

    logger.info("POST /admin/switch-league: id=%d name=%s", body.league_id, body.league_name)
    _active_league["id"] = body.league_id
    _active_league["name"] = body.league_name

    reset_progress()
    threading.Thread(
        target=agent_tools.switch_league,
        args=(body.league_name,),
        daemon=True,
    ).start()
    return {
        "status": "started",
        "message": f"Switching to '{body.league_name}'...",
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
    return PlayerListResponse(players=rows, count=len(rows))


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
