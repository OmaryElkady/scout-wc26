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
    # All "data" fields are optional — when the player is in a non-loaded league
    # the endpoint returns status="not_loaded" with just player_name + message +
    # suggested_league and the frontend renders a "switch league?" prompt
    # instead of trying to fill in the card.
    position: str = ""
    team: str = ""
    nationality: str = ""
    age: int | None = None
    jersey: int | None = None
    wins: int | None = None
    draws: int | None = None
    losses: int | None = None
    points: int | None = None
    matches: int | None = None
    summary: str = ""
    strengths: list[str] = []
    recommendation: str = ""
    status: str | None = None
    message: str | None = None
    suggested_league: str | None = None
    club: str | None = None


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
