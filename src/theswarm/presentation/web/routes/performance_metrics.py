"""Client-reported timing samples (#317).

The frontend times a click (route, action, how long it took) and posts it
here; stored next to the backend's own cycle/activity data so the two can be
correlated later. FastAPI validates the body against `PerformanceMetricCreate`
before the route body runs, so a missing field or a bad `duration_ms` never
reaches the repo.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/v1")


class PerformanceMetricCreate(BaseModel):
    route: str
    action: str
    duration_ms: float = Field(ge=0)
    client_timestamp: datetime


class PerformanceMetricOut(BaseModel):
    id: int
    route: str
    action: str
    duration_ms: float
    client_timestamp: datetime
    created_at: datetime


@router.post("/metrics/performance", status_code=201)
async def create_performance_metric(payload: PerformanceMetricCreate, request: Request) -> JSONResponse:
    repo = getattr(request.app.state, "performance_metric_repo", None)
    if repo is None:
        raise HTTPException(status_code=503, detail="no database")
    record = await repo.create(
        route=payload.route,
        action=payload.action,
        duration_ms=payload.duration_ms,
        client_timestamp=payload.client_timestamp.isoformat(),
    )
    return JSONResponse(
        {
            "id": record["id"],
            "route": record["route"],
            "action": record["action"],
            "duration_ms": record["duration_ms"],
        },
        status_code=201,
    )
