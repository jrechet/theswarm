"""Requests — the one thing a customer writes (V3 M5).

`/requests` is the owner's inbox (what waits, what is planned and
building, per customer) and a member's own list; `/requests/new` is the
member's composer. The owner turns a request into a feature — a GitHub
issue on one of the customer's projects — or declines it with a reason.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.application.services.requests import RequestError
from theswarm.presentation.web.routes.customers import _refused, current_actor

log = logging.getLogger(__name__)
router = APIRouter()


def ago(moment: datetime, now: datetime | None = None) -> str:
    """'2 h ago', 'yesterday', '30 Sep' — the way a person says it."""
    now = now or datetime.now(timezone.utc)
    try:
        delta = now - moment.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError):
        return ""
    minutes = int(delta.total_seconds() // 60)
    if minutes < 2:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h ago"
    days = hours // 24
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    return moment.strftime("%d %b").lstrip("0")


async def _customer_of(state, customer_id: str):
    repo = getattr(state, "customer_repo", None)
    return await repo.get(customer_id) if repo is not None else None


async def request_row(state, request, customer=None) -> dict:
    """What a request shows: who, when, where it stands, its feature and demo."""
    base = state.base_path
    customer = customer or await _customer_of(state, request.customer_id)
    slug = customer.slug if customer is not None else "internal"
    projects = []
    feature_href = ""
    if customer is not None:
        try:
            projects = await state.project_repo.list_for_customer(customer.id)
        except Exception:  # noqa: BLE001
            projects = []
    if request.feature_repo and request.feature_issue_number:
        name = request.feature_repo.partition("/")[2]
        feature_href = f"{base}/c/{slug}/p/{name}/f/{request.feature_issue_number}"
    return {
        "request": request,
        "customer": customer,
        "customer_slug": slug,
        "customer_name": customer.name if customer is not None else "",
        "customer_initial": customer.initial if customer is not None else "?",
        "project_name": next((p.repo.name for p in projects if p.id == request.project_id), ""),
        "projects": [{"full_name": str(p.repo), "name": p.repo.name} for p in projects],
        "when": ago(request.created_at),
        "steps": request.steps(),
        "feature_href": feature_href,
        "feature_label": f"{request.feature_repo.partition('/')[2]}#{request.feature_issue_number}" if request.feature_issue_number else "",
        "demo_href": f"{base}/demos/{request.demo_report_id}" if request.demo_report_id else "",
    }


async def inbox_rows(state, limit: int = 50) -> list[dict]:
    """The requests waiting for the owner, oldest first, as rows."""
    service = getattr(state, "request_service", None)
    if service is None:
        return []
    return [await request_row(state, r) for r in await service.inbox(limit=limit)]


@router.get("/requests", response_class=HTMLResponse)
async def requests_page(request: Request, error: str = ""):
    state = request.app.state
    actor = await current_actor(request)
    service = getattr(state, "request_service", None)
    if actor is None or service is None:
        return _refused(request, actor)
    if actor.is_owner:
        inbox = await inbox_rows(state)
        open_ = [await request_row(state, r) for r in await service.open_requests() if r.status != "received"]
        return state.templates.TemplateResponse("requests.html", {
            "role": "owner", "inbox": inbox, "open": open_, "error": error,
        })
    customer = await _customer_of(state, actor.customer_id)
    if customer is None:
        return _refused(request, actor)
    mine = [await request_row(state, r, customer) for r in await service.for_customer(customer)]
    return state.templates.TemplateResponse("requests.html", {
        "role": "member", "mine": mine, "customer": customer, "actor": actor, "error": error,
    })


@router.get("/requests/new", response_class=HTMLResponse)
async def new_request(request: Request, error: str = ""):
    state = request.app.state
    actor = await current_actor(request)
    if actor is None or actor.is_owner:
        return _refused(request, actor)
    customer = await _customer_of(state, actor.customer_id)
    projects = await state.project_repo.list_for_customer(actor.customer_id) if customer is not None else []
    return state.templates.TemplateResponse("request_new.html", {
        "customer": customer, "actor": actor, "error": error,
        "projects": [{"full_name": str(p.repo), "name": p.repo.name} for p in projects],
    })


@router.post("/requests")
async def submit_request(request: Request, title: str = Form(default=""), body: str = Form(default=""),
                         project: str = Form(default="")):
    state = request.app.state
    base = state.base_path
    actor = await current_actor(request)
    service = getattr(state, "request_service", None)
    if actor is None or actor.is_owner or service is None:
        return _refused(request, actor)
    customer = await _customer_of(state, actor.customer_id)
    if customer is None:
        return _refused(request, actor)
    chosen = None
    for p in await state.project_repo.list_for_customer(actor.customer_id):
        if str(p.repo) == project:
            chosen = p
    try:
        await service.submit(customer, title, body, member_id=actor.member_id, author_name=actor.login, project=chosen)
    except RequestError as exc:
        return RedirectResponse(f"{base}/requests/new?error={str(exc).replace(' ', '+')}", status_code=303)
    return RedirectResponse(f"{base}/requests", status_code=303)


@router.post("/requests/{request_id}/plan")
async def plan_request(request: Request, request_id: str, project: str = Form(default=""),
                       title: str = Form(default=""), body: str = Form(default="")):
    """Turn a request into a feature: the issue on the chosen project."""
    state = request.app.state
    base = state.base_path
    actor = await current_actor(request)
    service = getattr(state, "request_service", None)
    if actor is None or not actor.is_owner or service is None:
        return _refused(request, actor)
    req = await service.get(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="No such request")
    customer = await _customer_of(state, req.customer_id)
    chosen = next((p for p in await state.project_repo.list_for_customer(req.customer_id) if str(p.repo) == project), None)
    if customer is None or chosen is None:
        return RedirectResponse(f"{base}/requests?error=Pick+one+of+the+customer%27s+projects", status_code=303)
    try:
        planned = await service.plan(req, customer, chosen, title=title or None, body=body or None)
    except RequestError as exc:
        return RedirectResponse(f"{base}/requests?error={str(exc).replace(' ', '+')}", status_code=303)
    except Exception:  # noqa: BLE001 — GitHub down: say so, keep the request
        log.exception("requests: planning %s failed", request_id)
        return RedirectResponse(f"{base}/requests?error=GitHub+did+not+answer", status_code=303)
    return RedirectResponse(f"{base}/c/{customer.slug}/p/{chosen.repo.name}/f/{planned.feature_issue_number}", status_code=303)


@router.post("/requests/{request_id}/decline")
async def decline_request(request: Request, request_id: str, reason: str = Form(default="")):
    state = request.app.state
    actor = await current_actor(request)
    service = getattr(state, "request_service", None)
    if actor is None or not actor.is_owner or service is None:
        return _refused(request, actor)
    req = await service.get(request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="No such request")
    await service.decline(req, reason)
    return RedirectResponse(f"{state.base_path}/requests", status_code=303)
