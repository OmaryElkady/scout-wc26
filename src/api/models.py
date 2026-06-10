from typing import Any

from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str


class ChartRequest(BaseModel):
    request: str


class QueryResponse(BaseModel):
    answer: str
    question: str
    page_actions: list[dict[str, Any]] = []


class ReportResponse(BaseModel):
    player_name: str
    position: str
    team: str
    nationality: str
    age: int | None = None
    jersey: int | None = None
    wins: int | None = None
    draws: int | None = None
    losses: int | None = None
    points: int | None = None
    matches: int | None = None
    summary: str
    strengths: list[str]
    recommendation: str


class TeamListResponse(BaseModel):
    teams: list[dict[str, Any]]
    status: str | None = None
    message: str | None = None
    kickoff: str | None = None


class PlayerListResponse(BaseModel):
    players: list[dict[str, Any]]
    count: int
    status: str | None = None
    message: str | None = None
    kickoff: str | None = None


class SwitchLeagueRequest(BaseModel):
    league_id: int
    league_name: str
