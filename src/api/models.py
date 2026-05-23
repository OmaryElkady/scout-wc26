from typing import Any

from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str


class ChartRequest(BaseModel):
    request: str


class QueryResponse(BaseModel):
    answer: str
    question: str


class ReportResponse(BaseModel):
    player_name: str
    position: str
    team: str
    nationality: str
    age: int | None = None
    summary: str
    strengths: list[str]
    recommendation: str


class TeamListResponse(BaseModel):
    teams: list[dict[str, Any]]


class PlayerListResponse(BaseModel):
    players: list[dict[str, Any]]
    count: int
