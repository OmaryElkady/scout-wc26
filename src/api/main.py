import logging
import os
import pathlib
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
    TeamListResponse,
)
from src.utils.bq_client import bq
from src.utils.config import config

logger = logging.getLogger(__name__)


def _esc(s: str) -> str:
    return s.replace("'", "''")


_MODEL = "gemini-2.5-flash"
_DEMO_HTML = pathlib.Path(__file__).parent.parent.parent / "docs" / "demo.html"

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


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    logger.info("POST /query: question=%r", request.question)
    answer = scout_agent.run_query(request.question)
    return QueryResponse(answer=answer, question=request.question)


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

    client = genai.Client(vertexai=True, project=config.PROJECT_ID, location=config.REGION)

    plan_prompt = (
        f'You are a data visualization expert building charts from BigQuery.\n\n'
        f'User wants to see: "{body.request}"\n\n'
        f"Available BigQuery tables:\n"
        f"- `{table_ps}` (gold_player_stats): player_id, name, team_id, team_name, "
        f"position, nationality, age, jersey_number, league_id\n"
        f"- `{table_ts}` (gold_team_summary): team_id, team_name, matches_played, "
        f"wins, draws, losses, goals_for, goals_against, goal_difference, points\n\n"
        f"Return JSON with exactly these keys (raw JSON, no markdown):\n"
        f'{{"sql": "SELECT ...", "chart_type": "bar", "title": "..."}}\n\n'
        f"SQL rules: SELECT only, 2 columns (string label first, number second), LIMIT 20 max.\n"
        f"chart_type must be exactly one of: bar, line, doughnut."
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


@app.post("/report/pdf/{player_name}")
def report_pdf(player_name: str) -> Response:
    from io import BytesIO

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    logger.info("POST /report/pdf/%s", player_name)

    player = agent_tools.get_player_detail(player_name=player_name)
    if not player:
        raise HTTPException(status_code=404, detail=f"Player '{player_name}' not found")

    team_name = player.get("team_name", "")
    team = agent_tools.query_team_summary(team_name=team_name) if team_name else {}
    roster = agent_tools.get_team_roster(team_name=team_name) if team_name else []

    _wins = team.get("wins", 0) if team else 0
    _draws = team.get("draws", 0) if team else 0
    _losses = team.get("losses", 0) if team else 0
    _points = team.get("points", 0) if team else 0
    scouting_para = scout_agent.run_query(
        f"You are a professional football scout writing a scouting report. "
        f"Write a 3-4 sentence scouting assessment for {player.get('name', player_name)}, "
        f"aged {player.get('age', 'unknown')}, who plays {player.get('position', 'unknown')} "
        f"for {player.get('team_name', 'unknown')} (nationality: {player.get('nationality', 'unknown')}). "
        f"Their team has {_wins} wins, {_draws} draws, {_losses} losses and {_points} points. "
        f"\n\nWrite specifically about: their likely playing style for their position and age, "
        f"their value to the national team given the team's record, and one specific recommendation "
        f"(e.g. worth monitoring, strong prospect, established starter). "
        f"\n\nWrite in the style of a professional scout report. Be specific and direct. "
        f"Do not say you cannot assess players or that you lack domain expertise — just write the assessment."
    )

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    BLUE = colors.HexColor("#1f6feb")
    MUTED = colors.HexColor("#586069")
    LIGHT = colors.HexColor("#f6f8fa")
    BORDER = colors.HexColor("#e1e4e8")

    def _style(name, **kw):
        return ParagraphStyle(name, **kw)

    header_style = _style("hdr", fontName="Helvetica-Bold", fontSize=13, textColor=BLUE, spaceAfter=2)
    name_style = _style("nm", fontName="Helvetica-Bold", fontSize=22, spaceAfter=14)
    section_style = _style("sec", fontName="Helvetica-Bold", fontSize=12, textColor=BLUE, spaceBefore=14, spaceAfter=6)
    body_style = _style("bd", fontName="Helvetica", fontSize=11, leading=16, spaceAfter=4)
    label_style = _style("lbl", fontName="Helvetica-Bold", fontSize=10, textColor=MUTED, spaceAfter=2)
    footer_style = _style("ftr", fontName="Helvetica-Oblique", fontSize=9, textColor=MUTED, alignment=1)

    story = []

    story.append(Paragraph("Scout WC26 — Player Scouting Report", header_style))
    story.append(Spacer(1, 0.08 * inch))
    story.append(Paragraph(player.get("name", player_name), name_style))

    info_data = [
        ["Position", player.get("position", "—")],
        ["Age", str(player.get("age", "—"))],
        ["Nationality", player.get("nationality", "—")],
        ["Team", player.get("team_name", "—")],
        ["Jersey #", str(player.get("jersey_number", "—"))],
    ]
    info_tbl = Table(info_data, colWidths=[1.4 * inch, 4.5 * inch])
    info_tbl.setStyle(
        TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 11),
            ("TEXTCOLOR", (0, 0), (0, -1), BLUE),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [LIGHT, colors.white]),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ])
    )
    story.append(info_tbl)

    story.append(Paragraph("Team Performance", section_style))
    if team:
        perf_data = [
            ["W", "D", "L", "GF", "GA", "Pts"],
            [
                str(team.get("wins", "—")),
                str(team.get("draws", "—")),
                str(team.get("losses", "—")),
                str(team.get("goals_for", "—")),
                str(team.get("goals_against", "—")),
                str(team.get("points", "—")),
            ],
        ]
        perf_tbl = Table(perf_data, colWidths=[0.9 * inch] * 6)
        perf_tbl.setStyle(
            TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), LIGHT),
                ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ])
        )
        story.append(perf_tbl)
    else:
        story.append(Paragraph("No team data available.", body_style))

    story.append(Paragraph("Squad Roster", section_style))
    if roster:
        pos_groups: dict[str, list[str]] = {}
        for p in roster:
            pos = p.get("position", "UNKNOWN")
            pos_groups.setdefault(pos, []).append(p.get("name", ""))
        for pos in ["GK", "DEF", "MID", "FWD", "UNKNOWN"]:
            names = pos_groups.get(pos)
            if names:
                story.append(Paragraph(pos, label_style))
                story.append(Paragraph(", ".join(names), body_style))
    else:
        story.append(Paragraph("No roster data available.", body_style))

    story.append(Paragraph("Scouting Assessment", section_style))
    story.append(Paragraph(scouting_para or "No assessment available.", body_style))

    story.append(Spacer(1, 0.4 * inch))
    story.append(Paragraph("Generated by Scout WC26 | Powered by Gemini + BigQuery", footer_style))

    doc.build(story)
    buffer.seek(0)

    safe_name = player.get("name", player_name).replace(" ", "_")
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
def teams() -> TeamListResponse:
    logger.info("GET /teams")
    sql = "SELECT * FROM `" + config.table("gold_team_summary") + "` LIMIT 100"
    rows = bq.run_query(sql)
    return TeamListResponse(teams=rows)


@app.post("/refresh")
def refresh() -> dict:
    logger.info("POST /refresh")
    return agent_tools.refresh_scouting_data()


@app.get("/players", response_model=PlayerListResponse)
def players(
    position: Optional[str] = None,
    team_name: Optional[str] = None,
    nationality: Optional[str] = None,
) -> PlayerListResponse:
    logger.info(
        "GET /players: position=%s team_name=%s nationality=%s",
        position,
        team_name,
        nationality,
    )
    rows = agent_tools.query_players(
        position=position,
        team_name=team_name,
        nationality=nationality,
    )
    rows = rows[:50]
    return PlayerListResponse(players=rows, count=len(rows))


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
