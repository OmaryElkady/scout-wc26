import logging
import pathlib
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from src.agent import scout_agent
from src.agent import tools as agent_tools
from src.api.models import (
    PlayerListResponse,
    QueryRequest,
    QueryResponse,
    ReportResponse,
    TeamListResponse,
)
from src.utils.bq_client import bq
from src.utils.config import config

logger = logging.getLogger(__name__)

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
