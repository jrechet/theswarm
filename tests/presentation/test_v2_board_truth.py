"""The board says what is happening, not what the labels say.

concert-tour-app's board read "Building 17" with nothing running: issues
labelled `status:in-progress` since April by cycles long gone, 22 "in
review" with no pull request open. "Building" is now what a running cycle
works on (its pinned issue and that issue's sub-tasks); "In review" is an
issue with an open PR; the rest of those labels is "Stalled" — still one
Play away. The labels themselves are left as they are.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.api import CycleRequest, CycleStatus, get_cycle_tracker
from theswarm.application.events.bus import EventBus
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

REPO = "jrechet/concert-tour-app"



async def _v3(client, path, **kw):
    """A V2 address registers the project and redirects (303, under the base
    path); the page itself is read at its V3 address inside Internal."""
    await client.get(path.split("?")[0], **kw)
    return await client.get(path.replace("/r/jrechet/", "/c/internal/p/"), **kw)

def _issue(number, status, title, body=""):
    return {"number": number, "title": title, "labels": [f"status:{status}"],
            "state": "open", "body": body}


ISSUES = [
    _issue(21, "in-progress", "Fans can join a waiting list"),
    _issue(22, "in-progress", "Waiting list model", "Parent: #21"),
    _issue(218, "in-progress", "Display an almost-sold-out badge"),  # since 2026-09-13
    _issue(40, "review", "Notify on freed seat"),
    _issue(41, "review", "Old review, PR long merged"),
    _issue(50, "ready", "Paginate the concert list"),
]
OPEN_PRS = [{"number": 90, "title": "[#40] Notify on freed seat", "body": "Closes #40"}]


@pytest.fixture()
async def web(tmp_path):
    conn = await init_db(str(tmp_path / "board.db"))
    app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
                         EventBus(), SSEHub(), base_path="", db=conn)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        yield client
    await conn.close()


async def _board(client, prs=OPEN_PRS, running_issue: int | None = None) -> str:
    tracker = get_cycle_tracker()
    record = None
    if running_issue is not None:
        record = tracker.create(CycleRequest(repo=REPO, issue_number=running_issue))
        tracker.update_status(record.id, CycleStatus.RUNNING)
    try:
        with patch("theswarm.tools.github.GitHubClient") as klass:
            klass.return_value.get_issues = AsyncMock(return_value=list(ISSUES))
            klass.return_value.get_open_pr_briefs = (
                AsyncMock(side_effect=prs) if isinstance(prs, Exception) else AsyncMock(return_value=prs))
            return (await _v3(client, f"/r/{REPO}")).text
    finally:
        if record is not None:
            tracker._cycles.pop(record.id, None)


def _group(html: str, key: str) -> str:
    start = html.find(f'aria-labelledby="group-{key}"')
    if start == -1:
        return ""
    end = html.find("</section>", start)
    return html[start:end]


async def test_nothing_running_means_nothing_building(web):
    html = await _board(web)

    assert "Display an almost-sold-out badge" not in _group(html, "in-progress")
    assert "Waiting list model" not in _group(html, "in-progress")
    stalled = _group(html, "stalled")
    assert "Display an almost-sold-out badge" in stalled and "Waiting list model" in stalled


async def test_the_running_cycle_s_story_and_its_sub_tasks_are_building(web):
    html = await _board(web, running_issue=21)

    building = _group(html, "in-progress")
    assert "Fans can join a waiting list" in building and "Waiting list model" in building
    assert "Display an almost-sold-out badge" in _group(html, "stalled")


async def test_in_review_needs_an_open_pull_request(web):
    html = await _board(web)

    assert "Notify on freed seat" in _group(html, "review")
    assert "Old review, PR long merged" in _group(html, "stalled")


async def test_a_stalled_issue_can_still_be_played(web):
    html = await _board(web)

    assert "/features/218/play" in _group(html, "stalled")


async def test_when_the_pull_requests_cannot_be_read_the_labels_are_believed(web):
    """Better the label's word than a guess: nothing is called stalled on a
    failed read."""
    html = await _board(web, prs=RuntimeError("502"))

    assert "Old review, PR long merged" in _group(html, "review")
