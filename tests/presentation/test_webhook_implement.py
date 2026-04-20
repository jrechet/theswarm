"""Sprint F P1 — /swarm implement webhook route integration."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.infrastructure.scheduling.webhook_handler import WebhookHandler
from theswarm.presentation.web.app import create_web_app


class _FakeVcs:
    def __init__(self) -> None:
        self.comments: list[tuple[int, str]] = []

    async def post_issue_comment(self, number: int, body: str) -> None:
        self.comments.append((number, body))


@pytest.fixture
async def wired(tmp_path):
    conn = await init_db(str(tmp_path / "impl.db"))
    project_repo = SQLiteProjectRepository(conn)
    cycle_repo = SQLiteCycleRepository(conn)
    await project_repo.save(Project(id="alpha", repo=RepoUrl("acme/alpha")))
    bus = EventBus()
    vcs = _FakeVcs()
    app = create_web_app(
        project_repo, cycle_repo, bus,
        vcs_factory=lambda repo: vcs,
    )
    app.state.webhook_handler = WebhookHandler()
    app.state.allowed_commenters = ["alice"]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c, app, vcs, cycle_repo
    await conn.close()


def _payload(body: str, user: str, repo: str = "acme/alpha") -> dict:
    return {
        "action": "created",
        "comment": {"body": body, "user": {"login": user}},
        "issue": {"number": 99, "html_url": f"https://github.com/{repo}/issues/99"},
        "repository": {"full_name": repo},
        "sender": {"login": user},
    }


async def test_allowed_user_triggers_cycle(wired):
    client, app, vcs, cycle_repo = wired
    started: list[str] = []
    orig_handle = app.state.run_cycle_handler.handle

    async def spy(cmd):
        started.append(cmd.triggered_by)
        return await orig_handle(cmd)

    app.state.run_cycle_handler.handle = spy

    resp = await client.post(
        "/webhooks/github",
        json=_payload("/swarm implement", "alice"),
        headers={"X-GitHub-Event": "issue_comment"},
    )
    assert resp.status_code == 200
    assert len(started) == 1
    assert "/swarm implement" in started[0]
    assert "#99" in started[0]
    assert vcs.comments == []


async def test_disallowed_user_gets_refusal_comment(wired):
    client, app, vcs, cycle_repo = wired
    started: list[str] = []
    orig_handle = app.state.run_cycle_handler.handle

    async def spy(cmd):
        started.append(cmd.triggered_by)
        return await orig_handle(cmd)

    app.state.run_cycle_handler.handle = spy

    resp = await client.post(
        "/webhooks/github",
        json=_payload("/swarm implement", "eve"),
        headers={"X-GitHub-Event": "issue_comment"},
    )
    assert resp.status_code == 200
    assert started == []
    assert len(vcs.comments) == 1
    number, body = vcs.comments[0]
    assert number == 99
    assert "@eve" in body
    assert "allowlist" in body.lower()


async def test_non_slash_comment_ignored(wired):
    client, app, vcs, cycle_repo = wired
    started: list[str] = []
    orig_handle = app.state.run_cycle_handler.handle

    async def spy(cmd):
        started.append(cmd.triggered_by)
        return await orig_handle(cmd)

    app.state.run_cycle_handler.handle = spy

    resp = await client.post(
        "/webhooks/github",
        json=_payload("LGTM", "alice"),
        headers={"X-GitHub-Event": "issue_comment"},
    )
    assert resp.status_code == 200
    assert started == []
    assert vcs.comments == []


async def test_slash_implement_on_unknown_repo_is_silent(wired):
    client, app, vcs, cycle_repo = wired
    resp = await client.post(
        "/webhooks/github",
        json=_payload("/swarm implement", "alice", repo="other/repo"),
        headers={"X-GitHub-Event": "issue_comment"},
    )
    assert resp.status_code == 200
    assert vcs.comments == []


async def test_wildcard_allowlist_lets_anyone_trigger(tmp_path):
    conn = await init_db(str(tmp_path / "impl2.db"))
    project_repo = SQLiteProjectRepository(conn)
    cycle_repo = SQLiteCycleRepository(conn)
    await project_repo.save(Project(id="alpha", repo=RepoUrl("acme/alpha")))
    bus = EventBus()
    vcs = _FakeVcs()
    app = create_web_app(
        project_repo, cycle_repo, bus,
        vcs_factory=lambda repo: vcs,
    )
    app.state.webhook_handler = WebhookHandler()
    app.state.allowed_commenters = ["*"]

    started: list[str] = []
    orig_handle = app.state.run_cycle_handler.handle

    async def spy(cmd):
        started.append(cmd.triggered_by)
        return await orig_handle(cmd)

    app.state.run_cycle_handler.handle = spy

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/webhooks/github",
            json=_payload("/swarm implement now", "random-person"),
            headers={"X-GitHub-Event": "issue_comment"},
        )
    assert resp.status_code == 200
    assert len(started) == 1
    await conn.close()
