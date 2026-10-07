"""Customers and members — Settings, the invitation door, a customer's page (V3 M2).

`/settings/customers` is the owner's: create a customer, give it
repositories, invite people; the invitation is a link shown once, sent by
the owner by hand. `/invite/{token}` is a member's door; `/c/{slug}` is a
customer's page, the owner's everywhere, a member's only for their own.
`/c/{twelve hex}` redirects to the theater (M4). Since M5 a member's page
is their overview — what is being built as four plain steps, the latest
demos, their requests — and the owner can look at it as they do
(`?as=member`).
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.application.services.customers import Actor, CustomerError
from theswarm.domain.customers.value_objects import looks_like_cycle_id
from theswarm.presentation.web import auth
from theswarm.presentation.web.routes.auth_routes import set_session_cookie

log = logging.getLogger(__name__)
router = APIRouter()


# ── Who asks ─────────────────────────────────────────────────────────


async def current_actor(request: Request) -> Actor | None:
    """The owner (a login or the access key) or an active member; None otherwise."""
    headers = {k.lower(): v for k, v in request.headers.items()}
    subject = auth.session_login(headers)
    kind, ident = auth.subject_parts(subject)
    if kind == "member":
        service = getattr(request.app.state, "customer_service", None)
        return await service.actor_for_member(ident) if service is not None else None
    if kind == "owner":
        return Actor(kind="owner", login=ident)
    if auth.bearer_is_access_key(headers) or auth.auth_disabled():
        return Actor(kind="owner", login="owner")
    return None


async def member_home(request: Request) -> RedirectResponse | None:
    """A member's `/` is their customer's page; anyone else gets None."""
    actor = await current_actor(request)
    if actor is None or actor.is_owner:
        return None
    service = request.app.state.customer_service
    customer = await service._customers.get(actor.customer_id)
    base = request.app.state.base_path
    return RedirectResponse(f"{base}/c/{customer.slug if customer else ''}", status_code=303)


def _refused(request: Request, actor: Actor | None) -> HTMLResponse:
    base = request.app.state.base_path
    return request.app.state.templates.TemplateResponse("v3/refused.html", {
        "home": f"{base}/", "name": actor.login if actor else "",
    }, status_code=403)


def _external_base(request: Request) -> str:
    """Where the instance is reached from outside: EXTERNAL_URL, else the request."""
    base = request.app.state.base_path
    external = os.environ.get("EXTERNAL_URL", "").rstrip("/")
    if external:
        return f"{external}{base}"
    return f"{str(request.base_url).rstrip('/')}{base}"


# ── Settings › Customers (the owner) ─────────────────────────────────


@router.get("/settings")
async def settings_root(request: Request) -> RedirectResponse:
    return RedirectResponse(f"{request.app.state.base_path}/settings/customers", status_code=303)


async def _customers_rows(state) -> list[dict]:
    service = state.customer_service
    rows = []
    for customer in await service.list_all():
        projects = await service.projects_of(customer)
        members = await service.members_of(customer)
        rows.append({
            "customer": customer,
            "projects": [str(p.repo) for p in projects],
            "members": len([m for m in members if m.state != "revoked"]),
            "since": customer.created_at.strftime("%b %Y"),
        })
    return rows


@router.get("/settings/customers", response_class=HTMLResponse)
async def settings_customers(request: Request, error: str = "") -> HTMLResponse:
    state = request.app.state
    return state.templates.TemplateResponse("v3/settings_customers.html", {
        "rows": await _customers_rows(state), "error": error,
    })


@router.post("/settings/customers")
async def create_customer(request: Request, name: str = Form(default="")):
    state = request.app.state
    base = state.base_path
    try:
        customer = await state.customer_service.create(name)
    except CustomerError as exc:
        return state.templates.TemplateResponse("v3/settings_customers.html", {
            "rows": await _customers_rows(state), "error": str(exc),
        }, status_code=400)
    return RedirectResponse(f"{base}/settings/customers/{customer.slug}", status_code=303)


async def _customer_context(request: Request, customer, **extra) -> dict:
    state = request.app.state
    service = state.customer_service
    projects = await service.projects_of(customer)
    assigned = {str(p.repo) for p in projects}
    others = sorted(str(p.repo) for p in await state.project_repo.list_all() if str(p.repo) not in assigned)
    members = await service.members_of(customer)
    return {
        "customer": customer,
        "projects": projects,
        "unassigned": others,
        "members": members,
        "invite_base": _external_base(request),
        **extra,
    }


@router.get("/settings/customers/{slug}", response_class=HTMLResponse)
async def settings_customer(request: Request, slug: str, error: str = "") -> HTMLResponse:
    state = request.app.state
    customer = await state.customer_service.by_slug(slug)
    if customer is None:
        return HTMLResponse("No such customer", status_code=404)
    return state.templates.TemplateResponse(
        "v3/settings_customer.html", await _customer_context(request, customer, error=error),
    )


@router.post("/settings/customers/{slug}/projects")
async def assign_project(request: Request, slug: str, full_name: str = Form(default="")):
    state = request.app.state
    base = state.base_path
    customer = await state.customer_service.by_slug(slug)
    if customer is None:
        return HTMLResponse("No such customer", status_code=404)
    try:
        await state.customer_service.assign_project(full_name, customer)
    except ValueError as exc:
        return state.templates.TemplateResponse(
            "v3/settings_customer.html",
            await _customer_context(request, customer, error=f"Not a repository name: {exc}"),
            status_code=400,
        )
    return RedirectResponse(f"{base}/settings/customers/{slug}", status_code=303)


@router.post("/settings/customers/{slug}/members")
async def invite_member(
    request: Request, slug: str, email: str = Form(default=""), display_name: str = Form(default=""),
):
    """Invite an email; the page comes back with the link, shown this once."""
    state = request.app.state
    customer = await state.customer_service.by_slug(slug)
    if customer is None:
        return HTMLResponse("No such customer", status_code=404)
    try:
        member, token = await state.customer_service.invite(customer, email, display_name)
    except CustomerError as exc:
        return state.templates.TemplateResponse(
            "v3/settings_customer.html",
            await _customer_context(request, customer, error=str(exc)), status_code=400,
        )
    invitation_url = f"{_external_base(request)}/invite/{token}"
    log.info("Customer %s: invited %s (member %s)", customer.slug, member.email, member.id)
    return state.templates.TemplateResponse(
        "v3/settings_customer.html",
        await _customer_context(request, customer, invited=member, invitation_url=invitation_url),
    )


@router.post("/settings/customers/{slug}/members/{member_id}/revoke")
async def revoke_member(request: Request, slug: str, member_id: str):
    state = request.app.state
    await state.customer_service.revoke(member_id)
    return RedirectResponse(f"{state.base_path}/settings/customers/{slug}", status_code=303)


# ── The invitation door (public) ─────────────────────────────────────


@router.get("/invite/{token}")
async def accept_invitation(request: Request, token: str):
    state = request.app.state
    base = state.base_path
    service = getattr(state, "customer_service", None)
    member = await service.accept(token) if service is not None else None
    if member is None:
        return RedirectResponse(
            f"{base}/login?error=This+invitation+is+not+valid+any+more", status_code=303,
        )
    customer = await service._customers.get(member.customer_id)
    response = RedirectResponse(f"{base}/c/{customer.slug if customer else ''}", status_code=303)
    set_session_cookie(response, request, auth.member_subject(member.id))
    log.info("Member %s accepted the invitation to %s", member.id, member.customer_id)
    return response


# ── A customer's page ────────────────────────────────────────────────


@router.get("/c/{slug}", response_class=HTMLResponse)
async def customer_page(request: Request, slug: str):
    state = request.app.state
    actor = await current_actor(request)
    service = getattr(state, "customer_service", None)
    customer = None
    if service is not None and not looks_like_cycle_id(slug):
        customer = await service.by_slug(slug)
    if customer is None:
        # Not a customer: the theater's V2 address, kept alive for every
        # link already shared — the owner's only; a member is refused.
        if actor is None or not actor.is_owner:
            return _refused(request, actor)
        from theswarm.presentation.web.routes.theater import theater_target

        target = await theater_target(state, slug)
        if target is None:
            return HTMLResponse("Cycle not found", status_code=404)
        return RedirectResponse(f"{state.base_path}/cycles/{target}", status_code=303)
    if actor is None or (not actor.is_owner and actor.customer_id != customer.id):
        return _refused(request, actor)
    if not actor.is_owner:
        await service.seen(actor.member_id)
    as_member = actor.is_owner and request.query_params.get("as") == "member"
    member_view = (not actor.is_owner) or as_member
    projects = await service.projects_of(customer)
    members = await service.members_of(customer) if actor.is_owner else []
    context = {
        "customer": customer,
        "projects": [{"full_name": str(p.repo), "name": p.repo.name, "owner": p.repo.owner,
                      "href": f"{state.base_path}/c/{customer.slug}/p/{p.repo.name}"} for p in projects],
        "members": [m for m in members if m.state != "revoked"],
        "is_owner": actor.is_owner,
        "actor": actor,
        "as_member": as_member,
        "member_view": member_view,
    }
    if member_view:
        context.update(await member_overview(state, customer, projects))
    return state.templates.TemplateResponse("v3/customer.html", context)


# ── A member's overview (V3 M5) ──────────────────────────────────────


async def _feature_title(full_name: str, number: int | None) -> str:
    """The pinned issue's title, from the cache; '' when GitHub does not answer."""
    if not number:
        return ""
    from theswarm.application.services.pinned_issue import load_pinned_issue

    try:
        pinned = await load_pinned_issue(full_name, number)
    except Exception:  # noqa: BLE001 — the overview stays
        log.exception("member overview: reading %s#%s failed", full_name, number)
        return ""
    return (pinned.issue or {}).get("title", "") if pinned.issue else ""


def _demo_row(state, report, project_name: str) -> dict:
    """A demo as a member's list shows it: the title, the verdict, when."""
    from theswarm.presentation.web.routes import player, v2

    base = state.base_path
    card = v2._demo_card(state, report)
    verdict = player.verdict_of(report.quality_gates)
    label, kind = {"verified": ("Verified", "verified"), "broken": ("Broken", "broken")}.get(verdict, ("Unverified", "unverified"))
    title = report.stories[0].title if report.stories else f"Cycle {str(report.cycle_id)[:8]}"
    if len(report.stories) > 1:
        title = f"{title} + {len(report.stories) - 1} more"
    return {
        "id": report.id, "href": f"{base}/demos/{report.id}", "title": title, "project": project_name,
        "created_at": report.created_at, "when": player._when(report.created_at),
        "thumbnail": card["thumbnail_url"], "duration": "",
        "verdict": verdict, "verdict_label": label, "verdict_kind": kind,
    }


async def member_overview(state, customer, projects) -> dict:
    """What a member's /c/{slug} shows: what is being built (four plain
    steps), the latest demos, their requests, three counts — never a cost,
    never a link into the theater."""
    from theswarm.application.services.progress_bridge import get_phase_history
    from theswarm.presentation.web.member_steps import stage_for
    from theswarm.presentation.web.routes import v2

    base = state.base_path
    building: list[dict] = []
    demos: list[dict] = []
    requests: list[dict] = []
    report_repo = getattr(state, "report_repo", None)
    for project in projects:
        full_name = str(project.repo)
        record = v2._running_for_repo(full_name)
        if record is not None:
            history = get_phase_history(record.id)
            phase = history[-1].get("phase", "") if history else ""
            number = getattr(record, "issue_number", None)
            title = await _feature_title(full_name, number) or (f"Feature #{number}" if number else "The next feature")
            href = f"{base}/c/{customer.slug}/p/{project.repo.name}/f/{number}" if number else f"{base}/c/{customer.slug}"
            building.append({"title": title, "project": project.repo.name, "href": href, "number": number,
                             "stage": stage_for(phase, getattr(record.status, "value", str(record.status)))})
        if report_repo is None:
            continue
        for key in {project.id, full_name}:
            try:
                reports = await report_repo.list_by_project(key, limit=6)
            except Exception:  # noqa: BLE001
                log.exception("member overview: listing the demos of %s failed", key)
                continue
            demos += [_demo_row(state, r, project.repo.name) for r in reports]
    demos.sort(key=lambda d: d["created_at"], reverse=True)
    service = getattr(state, "request_service", None)
    if service is not None:
        from theswarm.presentation.web.routes.requests_routes import request_row

        try:
            requests = [await request_row(state, r, customer) for r in await service.for_customer(customer, limit=8)]
        except Exception:  # noqa: BLE001
            log.exception("member overview: reading the requests of %s failed", customer.slug)
    open_requests = sum(1 for r in requests if r["request"].is_open)
    return {
        "building": building,
        "demos": demos[:6],
        "requests": requests,
        "stats": [
            {"n": len(building), "label": "being built", "color": "text-live-deep" if building else "text-ink"},
            {"n": len(demos), "label": "demo" + ("s" if len(demos) != 1 else ""), "color": "text-ink"},
            {"n": open_requests, "label": "open request" + ("s" if open_requests != 1 else ""), "color": "text-ink"},
        ],
    }
