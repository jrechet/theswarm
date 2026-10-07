"""The demo — the player on V3 (M4, docs/plans/2026-10-v3-one-product.md).

`/demos/{id}` is what a cycle delivered: the verdict, the video QA
recorded, what QA measured (the gates), what was built (a story per PR),
who can see it. `/demos/{id}/play` (V1) redirects here; `/d/{short}` stays
the public, read-only address the announcer never used and the owner
can hand out.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.presentation.web.routes import v2

log = logging.getLogger(__name__)
router = APIRouter()
public_router = APIRouter()

GATE_LABELS = {
    "unit_tests": ("Unit tests", "the target's own suite, in its venv"),
    "e2e_tests": ("Whole-API E2E", "the rest of the file, reported not judged"),
    "feature_e2e": ("Feature tests", "E2E tests written for this feature"),
    "feature_pages": ("Feature pages", "the pages the PRs added, walked"),
    "feature_calls": ("Feature calls", "the feature's own requests, played"),
    "security": ("Security", "semgrep OWASP · bandit"),
    "coverage": ("Coverage", "statements, this suite"),
    "cycle_completion": ("The cycle", "every phase ran to its end"),
}
GATE_KINDS = {"pass": "ok", "fail": "bad", "warn": "unverified", "skip": "waiting"}
BEHAVIOUR_GATES = ("feature_e2e", "feature_pages", "feature_calls")
VERDICTS = {
    "verified": ("Behaviour verified on the running app", "verified"),
    "broken": ("Built, but the running app says otherwise", "broken"),
    "unverified": ("Delivered — not fully checked on the running app", "unverified"),
}


def verdict_of(gates) -> str:
    """What the running app said: the harness's rule, read off the report's
    behaviour gates — any failing is broken, one passing and none failing
    is verified, anything else unverified."""
    statuses = [str(getattr(g.status, "value", g.status)) for g in gates if g.name in BEHAVIOUR_GATES]
    if "fail" in statuses:
        return "broken"
    if "pass" in statuses:
        return "verified"
    return "unverified"


def gate_rows(gates) -> list[dict]:
    rows = []
    for g in gates:
        status = str(getattr(g.status, "value", g.status))
        label, about = GATE_LABELS.get(g.name, (g.name.replace("_", " ").capitalize(), ""))
        value = g.detail or ""
        if g.name == "coverage" and g.value is not None and not value:
            value = f"{g.value:.0f}%"
        rows.append({"name": g.name, "label": label, "about": about, "status": status,
                     "kind": GATE_KINDS.get(status, "waiting"), "value": value})
    return rows


def _art(base: str, path: str) -> str:
    return f"{base}/artifacts/{path}" if path else ""


def story_cards(report, base: str) -> list[dict]:
    cards = []
    for s in report.stories:
        shots = [a for a in (*s.screenshots_after, *s.screenshots_before) if a.path]
        cards.append({
            "ticket_id": s.ticket_id, "title": s.title, "status": s.status,
            "pr_number": s.pr_number, "pr_url": s.pr_url,
            "files": s.files_changed, "added": s.lines_added, "removed": s.lines_removed,
            "thumbnail": _art(base, shots[0].path) if shots else "",
            "caption": shots[0].label if shots else "",
            "merged": s.status == "completed",
        })
    return cards


def _when(moment: datetime) -> str:
    try:
        return moment.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC").lstrip("0")
    except (AttributeError, ValueError):
        return ""


async def _cycle_facts(state, report) -> dict:
    """What the cycle's row knows: the feature, the duration, the repository's page."""
    facts = {"issue_number": None, "duration": "", "cost": "", "cycle_href": "", "project": None}
    base = state.base_path
    facts["cycle_href"] = f"{base}/cycles/{report.cycle_id}"
    cycle_repo = getattr(state, "cycle_repo", None)
    if cycle_repo is not None:
        try:
            from theswarm.domain.cycles.value_objects import CycleId

            cycle = await cycle_repo.get(CycleId(str(report.cycle_id)))
        except Exception:  # noqa: BLE001
            cycle = None
        if cycle is not None:
            facts["issue_number"] = cycle.issue_number
            if cycle.started_at and cycle.completed_at:
                minutes = int((cycle.completed_at - cycle.started_at).total_seconds() // 60)
                facts["duration"] = f"{minutes} min"
            if cycle.total_cost_usd:
                facts["cost"] = f"${cycle.total_cost_usd:.2f}"
    if not facts["cost"] and report.summary.cost_usd:
        facts["cost"] = f"${report.summary.cost_usd:.2f}"
    try:
        project = next((p for p in await state.project_repo.list_all() if str(p.repo) == report.project_id), None)
    except Exception:  # noqa: BLE001
        project = None
    customer = None
    customer_repo = getattr(state, "customer_repo", None)
    if project is not None and customer_repo is not None:
        try:
            customer = await customer_repo.get(project.customer_id)
        except Exception:  # noqa: BLE001
            customer = None
    members = 0
    service = getattr(state, "customer_service", None)
    if customer is not None and service is not None:
        try:
            members = len([m for m in await service.members_of(customer) if m.is_active])
        except Exception:  # noqa: BLE001
            members = 0
    slug = customer.slug if customer is not None else "internal"
    name = project.repo.name if project is not None else report.project_id.partition("/")[2]
    facts["project"] = {
        "name": name, "full_name": report.project_id,
        "href": f"{base}/c/{slug}/p/{name}" if project is not None else f"{base}/r/{report.project_id}",
        "feature_href": f"{base}/c/{slug}/p/{name}/f/" if project is not None else "",
        "customer_name": customer.name if customer is not None else "Internal",
        "customer_href": f"{base}/c/{slug}",
        "members": members,
        "settings_href": f"{base}/settings/customers/{slug}",
    }
    return facts


async def player_context(request: Request, report, *, public: bool) -> dict:
    state = request.app.state
    base = state.base_path
    card = v2._demo_card(state, report)
    facts = await _cycle_facts(state, report)
    verdict = verdict_of(report.quality_gates)
    verdict_label, verdict_kind = VERDICTS[verdict]
    title = report.stories[0].title if report.stories else f"Cycle {str(report.cycle_id)[:8]}"
    if len(report.stories) > 1:
        title = f"{title} + {len(report.stories) - 1} more"
    screenshots = [_art(base, a.path) for a in report.artifacts if a.type.value == "screenshot" and a.path]

    prev_demo = next_demo = None
    report_repo = getattr(state, "report_repo", None)
    if report_repo is not None and not public:
        try:
            siblings = await report_repo.list_by_project(report.project_id, limit=50)
            for i, r in enumerate(siblings):
                if r.id == report.id:
                    next_demo = siblings[i - 1] if i > 0 else None
                    prev_demo = siblings[i + 1] if i + 1 < len(siblings) else None
                    break
        except Exception:  # noqa: BLE001
            log.exception("player: listing the demos of %s failed", report.project_id)

    return {
        "report": report,
        "public": public,
        "title": title,
        "when": _when(report.created_at),
        "verdict": verdict, "verdict_label": verdict_label, "verdict_kind": verdict_kind,
        "video_url": card["video_url"], "poster_url": card["thumbnail_url"],
        "screenshots": screenshots[:8],
        "gates": gate_rows(report.quality_gates),
        "stories": story_cards(report, base),
        "summary": report.summary,
        "prev_url": f"{base}/demos/{prev_demo.id}" if prev_demo else "",
        "next_url": f"{base}/demos/{next_demo.id}" if next_demo else "",
        "public_url": f"{base}/d/{report.public_slug}",
        **facts,
    }


async def _report(request: Request, report_id: str):
    report_repo = getattr(request.app.state, "report_repo", None)
    if report_repo is None:
        return None
    try:
        return await report_repo.get(report_id)
    except Exception:  # noqa: BLE001
        log.exception("player: reading report %s failed", report_id)
        return None


@router.get("/demos/{report_id}/play")
async def legacy_play(request: Request, report_id: str):
    """The V1 player's address, kept alive for every link already shared."""
    return RedirectResponse(f"{request.app.state.base_path}/demos/{report_id}", status_code=303)


@router.get("/demos/{report_id}", response_class=HTMLResponse)
async def player(request: Request, report_id: str):
    report = await _report(request, report_id)
    if report is None:
        return HTMLResponse("No such demo", status_code=404)
    return request.app.state.templates.TemplateResponse(
        "v3/demo.html", await player_context(request, report, public=False),
    )


@public_router.get("/d/{short}", response_class=HTMLResponse)
async def public_player(request: Request, short: str):
    """Read-only, outside the wall, by the report's short slug."""
    report_repo = getattr(request.app.state, "report_repo", None)
    match = None
    if report_repo is not None:
        wanted = short.lower()
        for r in await report_repo.list_recent(limit=500):
            if r.public_slug == wanted:
                match = r
                break
    if match is None:
        return HTMLResponse("No such demo", status_code=404)
    return request.app.state.templates.TemplateResponse(
        "v3/demo_public.html", await player_context(request, match, public=True),
    )
