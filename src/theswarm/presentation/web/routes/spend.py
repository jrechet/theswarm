"""The owner's spend view as JSON (`/api/*` is the owner's by the wall; a
member's session never reaches it, and no customer page shows a cost)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/spend")
async def api_spend(request: Request) -> JSONResponse:
    """This month and last per customer, and the alerts the rows hold."""
    from theswarm.application.services.spend import spend_view

    state = request.app.state
    customer_repo = getattr(state, "customer_repo", None)
    if customer_repo is None:
        return JSONResponse({"detail": "Spend is not available (no database)"}, status_code=404)
    view = await spend_view(state.cycle_repo, state.project_repo, customer_repo)
    return JSONResponse(view.as_dict())
