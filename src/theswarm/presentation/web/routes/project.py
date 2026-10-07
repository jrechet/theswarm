"""The project and the feature (V3 M3, docs/plans/2026-10-v3-one-product.md).

`/c/{slug}/p/{name}` is a project inside its customer: the composer
(Create only / Create and play), the board — Backlog, Ready (stalled ones
named as such), Building, In review, Delivered — the trend of the last
harness runs, the recent cycles. `/f/{n}` is one feature: its sub-tasks,
its cycles, its demo. `/r/{owner}/{name}` (V2) redirects here.

The board's truth (what a running cycle works on is Building, an open PR
is In review, the rest of those labels is stalled) is V2's, kept in
`routes/v2.py` until M6 moves it here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.presentation.web.routes import v2

log = logging.getLogger(__name__)
router = APIRouter()

COLUMNS = (
    ("backlog", "Backlog", "bg-line-strong"),
    ("ready", "Ready", "bg-wait"),
    ("in-progress", "Building", "bg-live"),
    ("review", "In review", "bg-info"),
)
STATUS_CHIPS = {
    "backlog": ("Backlog", "waiting"),
    "ready": ("Ready", "waiting"),
    "in-progress": ("Building", "running"),
    "review": ("In review", "review"),
    "done": ("Done", "verified"),
    "dropped": ("Dropped", "waiting"),
    "stalled": ("Stalled", "waiting"),
}
CYCLE_CHIPS = {
    "running": ("Running", "running"),
    "queued": ("Queued", "waiting"),
    "pending": ("Queued", "waiting"),
    "completed": ("Completed", "verified"),
    "failed": ("Failed", "broken"),
    "cancelled": ("Cancelled", "waiting"),
}


# ── Where ────────────────────────────────────────────────────────────


async def _resolve(state, slug: str, name: str):
    """(customer, project) for /c/{slug}/p/{name}; (customer, None) or (None, None)."""
    service = getattr(state, "customer_service", None)
    customer = await service.by_slug(slug) if service is not None else None
    if customer is None:
        return None, None
    for project in await state.project_repo.list_for_customer(customer.id):
        if project.repo.name == name:
            return customer, project
    return customer, None


def urls_for(base: str, slug: str, name: str) -> dict:
    page = f"{base}/c/{slug}/p/{name}"
    return {
        "page": page,
        "features": f"{page}/features",
        "feature": f"{page}/f/",
        "play": f"{page}/features/",
        "customer": f"{base}/c/{slug}",
        "settings": f"{base}/settings/customers/{slug}",
    }


def _project_dict(customer, project, base: str) -> dict:
    full_name = str(project.repo)
    return {
        "full_name": full_name, "owner": project.repo.owner, "name": project.repo.name,
        "github_url": f"https://github.com/{full_name}",
        "memory_url": f"{base}/r/{full_name}/memory",
        "customer": customer,
    }


# ── The V2 address ───────────────────────────────────────────────────


@router.get("/r/{owner}/{name}")
async def legacy_repo(request: Request, owner: str, name: str, new: int | None = None):
    """A V2 link: the project's page in its customer (registered under Internal if new)."""
    state = request.app.state
    base = state.base_path
    await v2._ensure_project(state, owner, name)
    full_name = f"{owner}/{name}"
    slug = "internal"
    project = next((p for p in await state.project_repo.list_all() if str(p.repo) == full_name), None)
    repo = getattr(state, "customer_repo", None)
    if project is not None and repo is not None:
        customer = await repo.get(project.customer_id)
        if customer is not None:
            slug = customer.slug
    target = f"{base}/c/{slug}/p/{name}" + (f"?new={new}" if new else "")
    return RedirectResponse(target, status_code=303)


# ── The project page ─────────────────────────────────────────────────


def _clock(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%H:%M UTC")
    except (TypeError, ValueError):
        return ""


def _minutes(start, end) -> str:
    if not start or not end:
        return ""
    try:
        return f"{int((end - start).total_seconds() // 60)} min"
    except TypeError:
        return ""


async def _recent_cycles(state, project, base: str, limit: int = 6, issue_number: int | None = None) -> list[dict]:
    """The last cycles of a project (all of them, or one feature's), newest first."""
    cycle_repo = getattr(state, "cycle_repo", None)
    report_repo = getattr(state, "report_repo", None)
    if cycle_repo is None:
        return []
    try:
        cycles = await cycle_repo.list_by_project(project.id, limit=50 if issue_number else limit)
    except Exception:  # noqa: BLE001 — the page stays
        log.exception("project: listing cycles of %s failed", project.id)
        return []
    rows = []
    for c in cycles:
        if issue_number is not None and c.issue_number != issue_number:
            continue
        status = getattr(c.status, "value", str(c.status))
        label, kind = CYCLE_CHIPS.get(status, (status.capitalize(), "waiting"))
        demo_url = ""
        if report_repo is not None and status == "completed":
            try:
                reports = await report_repo.list_by_cycle(str(c.id), limit=1)
                if reports:
                    demo_url = f"{base}/demos/{reports[0].id}/play"
            except Exception:  # noqa: BLE001
                log.exception("project: reading the report of %s failed", c.id)
        rows.append({
            "id": str(c.id), "short": str(c.id)[:8], "href": f"{base}/c/{c.id}",
            "status": status, "label": label, "kind": kind,
            "issue_number": c.issue_number,
            "when": c.started_at.strftime("%d %b %H:%M") if c.started_at else "",
            "duration": _minutes(c.started_at, c.completed_at),
            "cost": f"${c.total_cost_usd:.2f}" if c.total_cost_usd else "",
            "prs_merged": len(c.prs_merged), "prs_opened": len(c.prs_opened),
            "demo_url": demo_url,
        })
        if len(rows) >= limit:
            break
    return rows


async def _delivered(state, full_name: str, base: str, limit: int = 6) -> list[dict]:
    """The latest demos of a project: the Delivered column."""
    report_repo = getattr(state, "report_repo", None)
    if report_repo is None:
        return []
    try:
        reports = await report_repo.list_by_project(full_name, limit=limit)
    except Exception:  # noqa: BLE001
        log.exception("project: reading the demos of %s failed", full_name)
        return []
    cycle_repo = getattr(state, "cycle_repo", None)
    cards = []
    for report in reports:
        card = v2._demo_card(state, report)
        issue_number = None
        if cycle_repo is not None:
            try:
                from theswarm.domain.cycles.value_objects import CycleId

                cycle = await cycle_repo.get(CycleId(str(report.cycle_id)))
                issue_number = cycle.issue_number if cycle is not None else None
            except Exception:  # noqa: BLE001
                issue_number = None
        gates = list(report.quality_gates)
        failed = [g for g in gates if str(getattr(g.status, "value", g.status)) == "fail"]
        title = report.stories[0].title if report.stories else ""
        card.update({
            "issue_number": issue_number,
            "title": title or (f"Cycle {str(report.cycle_id)[:8]}"),
            "when": v2._when(report.created_at),
            "gates_total": len(gates),
            "gates_label": "Gates pass" if not failed else f"{len(failed)} gate{'s' if len(failed) != 1 else ''} failed",
            "gates_kind": "ok" if not failed else "bad",
        })
        cards.append(card)
    return cards


def _issue_row(issue: dict, status: str, running, urls: dict) -> dict:
    number = issue.get("number")
    building = bool(running is not None and getattr(running, "issue_number", None) == number)
    return {
        "number": number, "title": issue.get("title", ""),
        "href": f"{urls['feature']}{number}",
        "play_url": f"{urls['play']}{number}/play",
        "building": building,
        "cycle_id": getattr(running, "id", "") if building else "",
        "stalled": status == "stalled",
        "fresh": False,
    }


@router.get("/c/{slug}/p/{name}", response_class=HTMLResponse)
async def project_page(request: Request, slug: str, name: str, new: int | None = None):
    state = request.app.state
    base = state.base_path
    customer, project = await _resolve(state, slug, name)
    if project is None:
        return HTMLResponse("No such project", status_code=404)
    full_name = str(project.repo)
    urls = urls_for(base, slug, name)

    issues: list[dict] = []
    issues_error = ""
    client = None
    try:
        from theswarm.tools.github import GitHubClient

        client = GitHubClient(full_name)
        issues = await v2._with_fresh_issue(client, await client.get_issues(), new)
    except Exception as exc:  # noqa: BLE001 — surfaced in the page banner
        log.exception("project: listing issues for %s failed", full_name)
        issues_error = str(exc)[:160]

    running = v2._running_for_repo(full_name)
    prs = await v2._open_pr_briefs(client) if client is not None and not issues_error else None
    by_key: dict[str, list[dict]] = {key: [] for key, _, _ in COLUMNS}
    stalled: list[dict] = []
    for issue in issues:
        status = v2._board_status(issue, running, prs)
        row = _issue_row(issue, status, running, urls)
        row["fresh"] = bool(new) and issue.get("number") == new
        if status == "stalled":
            stalled.append(row)
        else:
            by_key.get(status, by_key["backlog"]).append(row)
    columns = [{"key": key, "label": label, "dot": dot, "issues": by_key[key],
                "stalled": stalled if key == "ready" else []} for key, label, dot in COLUMNS]

    running_cycle = None
    if running is not None:
        running_cycle = {"id": running.id, "issue_number": running.issue_number,
                         "href": f"{base}/c/{running.id}", "since": _clock(running.started_at or running.created_at)}

    return state.templates.TemplateResponse("v3/project.html", {
        "customer": customer,
        "project": _project_dict(customer, project, base),
        "urls": urls,
        "columns": columns,
        "has_issues": bool(issues),
        "issues_error": issues_error,
        "running_cycle": running_cycle,
        "latest_demo": await v2._latest_demo(state, full_name),
        "delivered": await _delivered(state, full_name, base),
        "evals": await v2._evals_trend(state, full_name),
        "recent": await _recent_cycles(state, project, base),
    })


# ── The composer and Play ────────────────────────────────────────────


@router.post("/c/{slug}/p/{name}/features")
async def compose(request: Request, slug: str, name: str, body: str = Form(default=""),
                  play: str = Form(default="")):
    """Free text in, a GitHub issue out — and a cycle on it when asked."""
    state = request.app.state
    base = state.base_path
    customer, project = await _resolve(state, slug, name)
    if project is None:
        return HTMLResponse("No such project", status_code=404)
    urls = urls_for(base, slug, name)
    text = body.strip()
    if not text:
        return RedirectResponse(urls["page"], status_code=303)
    first_line, _, rest = text.partition("\n")
    title = first_line.strip()[:v2._COMPOSER_TITLE_MAX] or "Untitled feature"

    from theswarm.tools.github import GitHubClient

    created = await GitHubClient(str(project.repo)).create_issue(
        title=title, body=rest.strip(), labels=["status:backlog"],
    )
    number = created.get("number") if isinstance(created, dict) else None
    log.info("project: composed issue %r on %s (play=%s)", title, project.repo, bool(play))
    if not isinstance(number, int):
        return RedirectResponse(urls["page"], status_code=303)
    if play:
        record = await v2.start_targeted_cycle(
            state, project.repo.owner, project.repo.name, number, f"Play on issue #{number}",
        )
        return RedirectResponse(f"{base}/c/{record.id}", status_code=303)
    return RedirectResponse(f"{urls['page']}?new={number}", status_code=303)


@router.post("/c/{slug}/p/{name}/features/{number}/play")
async def play(request: Request, slug: str, name: str, number: int):
    state = request.app.state
    customer, project = await _resolve(state, slug, name)
    if project is None:
        return HTMLResponse("No such project", status_code=404)
    record = await v2.start_targeted_cycle(
        state, project.repo.owner, project.repo.name, number, f"Play on issue #{number}",
    )
    return RedirectResponse(f"{state.base_path}/c/{record.id}", status_code=303)


# ── One feature ──────────────────────────────────────────────────────


@router.get("/c/{slug}/p/{name}/f/{number}", response_class=HTMLResponse)
async def feature_page(request: Request, slug: str, name: str, number: int):
    state = request.app.state
    base = state.base_path
    customer, project = await _resolve(state, slug, name)
    if project is None:
        return HTMLResponse("No such project", status_code=404)
    full_name = str(project.repo)
    urls = urls_for(base, slug, name)

    from theswarm.application.services.pinned_issue import load_pinned_issue
    from theswarm.tools.github import issue_status

    pinned = await load_pinned_issue(full_name, number)
    if pinned.issue is None:
        return HTMLResponse(f"No such feature: #{number}", status_code=404)
    issue = pinned.issue
    running = v2._running_for_repo(full_name)
    building = bool(running is not None and getattr(running, "issue_number", None) == number)
    status = "in-progress" if building else ("done" if issue.get("state") == "closed" else issue_status(issue))
    label, kind = STATUS_CHIPS.get(status, (status, "waiting"))
    children = []
    for child in pinned.children:
        c_label, c_kind = STATUS_CHIPS.get(child.get("status", ""), (child.get("status", "open"), "waiting"))
        children.append({**child, "label": c_label, "kind": c_kind, "href": f"{urls['feature']}{child['number']}"})

    return state.templates.TemplateResponse("v3/feature.html", {
        "customer": customer,
        "project": _project_dict(customer, project, base),
        "urls": urls,
        "issue": {
            "number": number, "title": issue.get("title", ""), "body": issue.get("body") or "",
            "url": issue.get("html_url", f"https://github.com/{full_name}/issues/{number}"),
            "label": label, "kind": kind, "closed": issue.get("state") == "closed",
        },
        "children": children,
        "done": pinned.done,
        "building": building,
        "cycle_href": f"{base}/c/{running.id}" if building else "",
        "play_url": f"{urls['play']}{number}/play",
        "cycles": await _recent_cycles(state, project, base, limit=10, issue_number=number),
        "error": pinned.error,
    })
