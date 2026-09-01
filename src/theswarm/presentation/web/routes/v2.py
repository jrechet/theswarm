"""V2 — the one flow: pick a repo, write a feature, press Play, follow.

Server-rendered on the V2 template tree (Tailwind tokens, no CDN). Reuses
the proven plumbing underneath: GitHubClient for issues, the cycle tracker
+ run_api_cycle for Play (the #25 targeted-cycle mechanic), CreateProject
for silent registration when a repo is opened for the first time.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.application.commands.create_project import CreateProjectCommand
from theswarm.tools import github_app
from theswarm.tools.github import issue_status

log = logging.getLogger(__name__)

router = APIRouter(tags=["v2"])

_GROUPS = (
    ("in-progress", "Building"),
    ("review", "In review"),
    ("ready", "Ready"),
    ("backlog", "Backlog"),
)

_COMPOSER_TITLE_MAX = 80


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """The picker: repositories the owner confided to the GitHub App."""
    state = request.app.state
    creds = await github_app.load_credentials()

    repos: list[dict] = []
    seen: set[str] = set()
    if creds is not None:
        try:
            for r in await github_app.list_installation_repositories():
                full_name = r.get("full_name", "")
                owner, _, name = full_name.partition("/")
                repos.append({
                    "full_name": full_name, "owner": owner, "name": name,
                    "description": r.get("description") or "",
                    "private": bool(r.get("private")),
                    "language": r.get("language") or "",
                })
                seen.add(full_name)
        except Exception:  # noqa: BLE001 — GitHub down ≠ no home page
            log.exception("Listing installation repositories failed")

    # Registered projects that predate the App (or exist without it) stay
    # reachable — the flip to V2 must not orphan them.
    for project in await state.list_projects_query.execute():
        full_name = project.repo
        if full_name in seen or "/" not in full_name:
            continue
        owner, _, name = full_name.partition("/")
        repos.append({
            "full_name": full_name, "owner": owner, "name": name,
            "description": "", "private": False, "language": "",
        })

    install_url = ""
    if creds is not None and creds.html_url:
        install_url = f"{creds.html_url}/installations/new"

    return state.templates.TemplateResponse("v2/home.html", {
        "repos": repos,
        "app_configured": creds is not None,
        "install_url": install_url,
    })


async def _ensure_project(state, owner: str, name: str) -> str:
    """Return the project id for owner/name, registering it if new."""
    full_name = f"{owner}/{name}"
    for project in await state.list_projects_query.execute():
        if project.repo == full_name:
            return project.id

    handler = getattr(state, "create_project_handler", None)
    project_id = name.lower()
    existing_ids = {
        p.id for p in await state.list_projects_query.execute()
    }
    if project_id in existing_ids:
        project_id = f"{owner}-{name}".lower()
    if handler is None:
        return project_id
    try:
        await handler.handle(CreateProjectCommand(
            project_id=project_id, repo=full_name,
        ))
        log.info("V2: registered project %s for %s", project_id, full_name)
    except ValueError:
        pass  # raced with another request — the project exists now
    return project_id


def _running_for_repo(full_name: str) -> object | None:
    from theswarm.api import CycleStatus, get_cycle_tracker

    for record in get_cycle_tracker().list_recent(limit=50):
        if record.repo == full_name and record.status in (
            CycleStatus.QUEUED, CycleStatus.RUNNING,
        ):
            return record
    return None


@router.get("/r/{owner}/{name}", response_class=HTMLResponse)
async def repo_page(request: Request, owner: str, name: str) -> HTMLResponse:
    state = request.app.state
    full_name = f"{owner}/{name}"
    await _ensure_project(state, owner, name)

    issues: list[dict] = []
    issues_error = ""
    try:
        from theswarm.tools.github import GitHubClient

        issues = await GitHubClient(full_name).get_issues()
    except Exception as exc:  # noqa: BLE001 — surfaced in the page banner
        log.exception("V2: listing issues for %s failed", full_name)
        issues_error = str(exc)[:160]

    running = _running_for_repo(full_name)
    by_status: dict[str, list[dict]] = {key: [] for key, _ in _GROUPS}
    for issue in issues:
        status = issue_status(issue)
        row = dict(issue)
        row["building"] = bool(
            running is not None
            and getattr(running, "issue_number", None) == issue.get("number"),
        )
        row["cycle_id"] = getattr(running, "id", "") if row["building"] else ""
        by_status.get(status, by_status["backlog"]).append(row)

    groups = [
        {"key": key, "label": label, "issues": by_status[key]}
        for key, label in _GROUPS
    ]
    return state.templates.TemplateResponse("v2/repo.html", {
        "owner": owner, "repo_name": name,
        "groups": groups,
        "has_issues": bool(issues),
        "issues_error": issues_error,
        "running_cycle": running,
    })


@router.post("/r/{owner}/{name}/issues")
async def compose_issue(
    request: Request, owner: str, name: str, body: str = Form(default=""),
):
    """The composer: free text in, GitHub issue out."""
    base = request.app.state.base_path
    text = body.strip()
    back = RedirectResponse(f"{base}/r/{owner}/{name}", status_code=303)
    if not text:
        return back

    first_line, _, rest = text.partition("\n")
    title = first_line.strip()[:_COMPOSER_TITLE_MAX] or "Untitled feature"
    issue_body = rest.strip()

    from theswarm.tools.github import GitHubClient

    await GitHubClient(f"{owner}/{name}").create_issue(
        title=title, body=issue_body, labels=["status:backlog"],
    )
    log.info("V2: composed issue %r on %s/%s", title, owner, name)
    return back


@router.post("/r/{owner}/{name}/issues/{issue_number}/play")
async def play(
    request: Request, owner: str, name: str, issue_number: int,
):
    """Start a cycle pinned to one issue and follow it."""
    from theswarm.api import CycleRequest, get_cycle_tracker, run_api_cycle

    state = request.app.state
    full_name = f"{owner}/{name}"
    project_id = await _ensure_project(state, owner, name)

    tracker = get_cycle_tracker()
    record = tracker.create(
        CycleRequest(repo=full_name, issue_number=issue_number),
    )
    task = asyncio.create_task(
        run_api_cycle(
            record.id, full_name, f"Play on issue #{issue_number}", "",
            getattr(state, "allowed_repos", []),
            event_bus=getattr(state, "event_bus", None),
            report_repo=getattr(state, "report_repo", None),
            base_path=getattr(state, "base_path", ""),
            project_repo=getattr(state, "project_repo", None),
            cycle_repo=getattr(state, "cycle_repo", None),
            project_id=project_id,
            role_assignment_service=getattr(state, "role_assignment_service", None),
            issue_number=issue_number,
        ),
    )
    tracker.set_task(record.id, task)
    log.info("V2: Play #%d on %s → cycle %s", issue_number, full_name, record.id)

    base = state.base_path
    return RedirectResponse(f"{base}/cycles/{record.id}", status_code=303)
