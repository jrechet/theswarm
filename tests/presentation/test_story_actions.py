"""Sprint C F6 — Approve/Reject/Comment inline in player."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.domain.reporting.entities import (
    DemoReport,
    ReportSummary,
    StoryReport,
)
from theswarm.domain.reporting.events import (
    StoryApproved,
    StoryCommented,
    StoryRejected,
)
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


class FakeVCS:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def submit_review(self, pr_number: int, body: str, event: str) -> None:
        self.calls.append(("submit_review", pr_number, body, event))

    async def merge_pr(self, pr_number: int, method: str = "squash") -> None:
        self.calls.append(("merge_pr", pr_number, method))

    async def close_pr(self, pr_number: int) -> None:
        self.calls.append(("close_pr", pr_number))

    async def create_pr_comment(self, pr_number: int, body: str) -> None:
        self.calls.append(("create_pr_comment", pr_number, body))


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "story.db"))
    yield conn
    await conn.close()


@pytest.fixture
async def ctx(db):
    project_repo = SQLiteProjectRepository(db)
    cycle_repo = SQLiteCycleRepository(db)
    report_repo = SQLiteReportRepository(db)

    await project_repo.save(Project(id="alpha", repo=RepoUrl("o/alpha")))

    story = StoryReport(
        ticket_id="T-42",
        title="Add feature",
        status="completed",
        pr_number=7,
    )
    report = DemoReport(
        id="r-1",
        cycle_id=CycleId("cyc-1"),
        project_id="alpha",
        created_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        summary=ReportSummary(stories_completed=1, stories_total=1),
        stories=(story,),
    )
    await report_repo.save(report)

    bus = EventBus()
    events: dict[str, list] = {"approved": [], "rejected": [], "commented": []}

    async def _on_approve(evt: StoryApproved) -> None:
        events["approved"].append(evt)

    async def _on_reject(evt: StoryRejected) -> None:
        events["rejected"].append(evt)

    async def _on_comment(evt: StoryCommented) -> None:
        events["commented"].append(evt)

    bus.subscribe(StoryApproved, _on_approve)
    bus.subscribe(StoryRejected, _on_reject)
    bus.subscribe(StoryCommented, _on_comment)

    vcs = FakeVCS()
    app = create_web_app(
        project_repo, cycle_repo, bus, SSEHub(),
        report_repo=report_repo,
        db=db,
        vcs_factory=lambda repo: vcs,
    )
    return {"app": app, "vcs": vcs, "events": events, "report": report}


async def test_approve_story_publishes_event_and_merges_pr(ctx):
    transport = ASGITransport(app=ctx["app"])
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/demos/r-1/stories/T-42/approve",
            data={"actor": "alice"},
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True

    assert len(ctx["events"]["approved"]) == 1
    evt = ctx["events"]["approved"][0]
    assert evt.report_id == "r-1"
    assert evt.ticket_id == "T-42"
    assert evt.user == "alice"

    actions = {call[0] for call in ctx["vcs"].calls}
    assert "submit_review" in actions
    assert "merge_pr" in actions


async def test_approve_is_idempotent_second_returns_409(ctx):
    transport = ASGITransport(app=ctx["app"])
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r1 = await c.post("/demos/r-1/stories/T-42/approve", data={"actor": "alice"})
        r2 = await c.post("/demos/r-1/stories/T-42/approve", data={"actor": "alice"})
    assert r1.status_code == 200
    assert r2.status_code == 409


async def test_reject_story_publishes_event_and_closes_pr(ctx):
    transport = ASGITransport(app=ctx["app"])
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/demos/r-1/stories/T-42/reject",
            data={"actor": "bob", "comment": "needs rework"},
        )
    assert r.status_code == 200
    assert len(ctx["events"]["rejected"]) == 1
    evt = ctx["events"]["rejected"][0]
    assert evt.comment == "needs rework"
    assert evt.user == "bob"

    actions = {call[0] for call in ctx["vcs"].calls}
    assert "submit_review" in actions
    assert "close_pr" in actions


async def test_comment_story_posts_pr_comment(ctx):
    transport = ASGITransport(app=ctx["app"])
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/demos/r-1/stories/T-42/comment",
            data={"actor": "carol", "comment": "nit: rename var"},
        )
    assert r.status_code == 200
    assert len(ctx["events"]["commented"]) == 1

    actions = [call for call in ctx["vcs"].calls if call[0] == "create_pr_comment"]
    assert len(actions) == 1
    assert actions[0][1] == 7
    assert "nit: rename var" in actions[0][2]


async def test_comment_requires_non_empty_body(ctx):
    transport = ASGITransport(app=ctx["app"])
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post(
            "/demos/r-1/stories/T-42/comment",
            data={"actor": "carol", "comment": "   "},
        )
    assert r.status_code == 400


async def test_unknown_story_returns_404(ctx):
    transport = ASGITransport(app=ctx["app"])
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/demos/r-1/stories/T-999/approve", data={"actor": "alice"})
    assert r.status_code == 404


async def test_controls_rendered_on_private_player(ctx):
    transport = ASGITransport(app=ctx["app"])
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/demos/r-1/play")
    assert r.status_code == 200
    assert "story-action-form" in r.text
    assert "approve" in r.text
