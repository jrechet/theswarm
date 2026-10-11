"""What the V3 pages share (M6): the demo card, the board's truth, the
project registry, the running cycle, Play.

Moved out of the V2 module when V2 went (docs/plans/2026-10-v3-one-product.md,
M6); the names kept their underscore so the pages and the tests read as
before. `github_app` lives here so one patch target covers every page."""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime, timezone

from theswarm.application.commands.create_project import CreateProjectCommand
from theswarm.application.services.swr_cache import Swr
from theswarm.tools import github_app  # noqa: F401 — the home reads it through this module
from theswarm.tools.github import issue_status

log = logging.getLogger(__name__)


_PR_TASK_RE = re.compile(r"\[#(\d+)\]|\bCloses #(\d+)", re.IGNORECASE)


_COMPOSER_TITLE_MAX = 80


def _running_repos_safe() -> dict[str, object]:
    from theswarm.presentation.web.shell import running_repos

    try:
        return running_repos()
    except Exception:  # noqa: BLE001 — the home page stays
        log.exception("V2: reading the cycle tracker failed")
        return {}


def _clock(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%H:%M UTC")
    except (TypeError, ValueError):
        return ""


def _when(moment: datetime) -> str:
    """A demo's moment, the way a person says it: today 07:41, yesterday, 2 Oct."""
    try:
        moment = moment.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError):
        return ""
    today = datetime.now(timezone.utc).date()
    days = (today - moment.date()).days
    if days <= 0:
        return moment.strftime("today %H:%M")
    if days == 1:
        return "yesterday"
    return moment.strftime("%d %b").lstrip("0")


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


async def _latest_demo(state, full_name: str) -> dict | None:
    """The last demo the swarm recorded for this repository, if any.

    "Open the project and watch the demos": the report the QA phase writes
    after every cycle, surfaced where the owner starts from instead of
    three clicks into the legacy pages. Degrades to nothing — never to an
    error page — when the store is missing or unwell.
    """
    report_repo = getattr(state, "report_repo", None)
    if report_repo is None:
        return None
    try:
        reports = await report_repo.list_by_project(full_name, limit=1)
    except Exception:  # noqa: BLE001 — the page stays, the card degrades
        log.exception("V2: reading demo reports for %s failed", full_name)
        return None
    if not reports:
        return None
    return _demo_card(state, reports[0])


def _demo_card(state, report) -> dict:
    """What a demo card shows of a stored report: the repo page's latest
    demo, and the theater once its cycle is done."""
    base = state.base_path

    def art(path: str) -> str:
        return f"{base}/artifacts/{path}"

    screenshots = [a.path for a in report.artifacts if a.type.value == "screenshot" and a.path]
    videos = [a.path for a in report.artifacts if a.type.value == "video" and a.path]
    for story in report.stories:
        screenshots += [a.path for a in (*story.screenshots_after, *story.screenshots_before) if a.path]
        if story.video and story.video.path:
            videos.append(story.video.path)
    thumb = report.thumbnail_path
    return {
        "id": report.id,
        "cycle_id": str(report.cycle_id),
        "created_at": report.created_at,
        "play_url": f"{base}/demos/{report.id}",
        "thumbnail_url": art(thumb) if thumb else "",
        "video_url": art(videos[0]) if videos else "",
        "screenshots": [art(path) for path in screenshots[:4]],
        "screenshot_count": report.screenshot_count,
        "video_count": report.video_count,
        "prs_merged": report.summary.prs_merged,
        "prs_held": report.summary.prs_held,
        "stories_completed": report.summary.stories_completed,
        "stories_total": report.summary.stories_total,
        "cost_usd": report.summary.cost_usd,
    }


async def _with_fresh_issue(client, issues: list[dict], number: int | None) -> list[dict]:
    """The issue the composer just created, on the board even when GitHub's
    list has not caught up yet: the list trails a creation by seconds, a read
    by number does not. A closed or unreadable one stays off."""
    if not number or any(i.get("number") == number for i in issues):
        return issues
    try:
        issue = await client.get_issue(number)
    except Exception:  # noqa: BLE001 — the board without it, as GitHub has it
        log.warning("V2: reading the new issue #%s failed", number, exc_info=True)
        return issues
    if not issue or issue.get("state", "open") != "open":
        return issues
    return [issue, *issues]


async def _open_pr_briefs(client) -> list[dict] | None:
    """The open PRs, or None when they cannot be read — then the labels are
    believed, rather than an issue called stalled on a failed read."""
    try:
        return list(await client.get_open_pr_briefs())
    except Exception:  # noqa: BLE001 — the board keeps the labels' word
        log.warning("V2: listing open PRs failed", exc_info=True)
        return None


# The board's GitHub reads, kept like the pinned issue (`swr_cache`):
# espace-client's open issues took 2.2 s and its PRs 0.6 s more, one after
# the other, on every visit — 2.8 s for the page on prod (2026-10-11). Both
# are read side by side now, fresh 20 s, served while one read in the
# background refreshes them for ten minutes after; 0 in the suite.
def board_fresh_seconds() -> float:
    try:
        return float(os.environ.get("SWARM_BOARD_CACHE_SECONDS", 20))
    except ValueError:
        return 20.0


def board_keep_seconds() -> float:
    try:
        return float(os.environ.get("SWARM_BOARD_KEEP_SECONDS", 600))
    except ValueError:
        return 600.0


def board_timeout() -> float:
    return 20.0


_BOARD = Swr("board", fresh=board_fresh_seconds, keep=board_keep_seconds, timeout=board_timeout)


async def board_reads(repo: str) -> tuple[list[dict], list[dict] | None]:
    """The repository's open issues and its open PRs (None when they could
    not be read), from GitHub or kept. Raises when the issues cannot be read."""
    async def load():
        from theswarm.tools.github import GitHubClient

        client = await asyncio.to_thread(GitHubClient, repo)
        issues, prs = await asyncio.gather(client.get_issues(), _open_pr_briefs(client))
        return list(issues), prs

    return await _BOARD.get(repo, load)


# The home lists every repository the owner's token sees, page after page
# (0.5–1.2 s on prod): kept the same way, a minute fresh, an hour served.
_REPOS = Swr("repositories", fresh=lambda: 3 * board_fresh_seconds(), keep=lambda: 3600.0,
             timeout=board_timeout)


async def user_repositories() -> list[dict]:
    return await _REPOS.get("user", lambda: github_app.list_user_repositories())


def forget_board(repo: str) -> None:
    """The board's next read waits for GitHub: after the composer created an issue."""
    _BOARD.forget(repo)


def _board_status(issue: dict, running, prs: list[dict] | None) -> str:
    """The column an issue belongs in: its label, unless the label claims
    work nothing is doing (`stalled`)."""
    from theswarm.tools.github import is_child_of

    status = issue_status(issue)
    number = issue.get("number")
    if status == "in-progress":
        pinned = getattr(running, "issue_number", None) if running is not None else None
        if pinned is None or not (number == pinned or is_child_of(issue.get("body"), pinned)):
            return "stalled"
    if status == "review" and prs is not None:
        claimed = {int(n) for pr in prs
                   for pair in _PR_TASK_RE.findall(f"{pr.get('title', '')}\n{pr.get('body', '')}")
                   for n in pair if n}
        if number not in claimed:
            return "stalled"
    return status


async def _evals_trend(state, repo: str) -> dict:
    """The last harness runs on this repo (V2 M6): the runs the harness
    posted to the API first, the shipped docs/harness-runs.jsonl otherwise."""
    from theswarm import evals

    try:
        store = getattr(state, "eval_run_repo", None)
        entries = await store.list_for_repo(repo) if store is not None else []
        if not entries:
            entries = evals.read_history(evals.HISTORY_PATH, repo)
        return evals.trend(entries)
    except Exception:  # noqa: BLE001 — a page, not a judge
        log.exception("V2: reading the eval history for %s failed", repo)
        return evals.trend([])


async def start_targeted_cycle(state, owner: str, name: str, issue_number: int, description: str):
    """What ▶ Play does: a tracker record and a cycle pinned to the issue.

    The webhook doors (V2 M8) start cycles through here too, so a label and
    a click are the same thing to the tracker, the theater and the lock.
    """
    from theswarm.api import CycleRequest, get_cycle_tracker, run_api_cycle

    full_name = f"{owner}/{name}"
    project_id = await _ensure_project(state, owner, name)
    forget_board(full_name)  # the labels are about to move

    tracker = get_cycle_tracker()
    record = tracker.create(
        CycleRequest(repo=full_name, issue_number=issue_number, description=description),
    )
    task = asyncio.create_task(
        run_api_cycle(
            record.id, full_name, description, "",
            getattr(state, "allowed_repos", []),
            event_bus=getattr(state, "event_bus", None),
            report_repo=getattr(state, "report_repo", None),
            base_path=getattr(state, "base_path", ""),
            project_repo=getattr(state, "project_repo", None),
            cycle_repo=getattr(state, "cycle_repo", None),
            project_id=project_id,
            role_assignment_service=getattr(state, "role_assignment_service", None),
            checkpoint_repo=getattr(state, "checkpoint_repo", None),
            issue_number=issue_number,
        ),
    )
    tracker.set_task(record.id, task)
    log.info("V2: %s #%d on %s → cycle %s", description, issue_number, full_name, record.id)
    return record
