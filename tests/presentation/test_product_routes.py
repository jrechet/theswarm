"""Phase C presentation tests for PO intelligence routes."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.product.entities import Policy, Proposal, Signal
from theswarm.domain.product.value_objects import (
    ProposalStatus,
    SignalKind,
    SignalSeverity,
)
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "prodroutes.db"))
    yield conn
    await conn.close()


@pytest.fixture()
def app(db):
    bus = EventBus()
    hub = SSEHub()
    return create_web_app(
        SQLiteProjectRepository(db),
        SQLiteCycleRepository(db),
        bus,
        hub,
        db=db,
    )


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestProposalsRoutes:
    async def test_inbox_empty_by_default(self, client):
        r = await client.get("/projects/demo/proposals")
        assert r.status_code == 200
        assert "No pending proposals" in r.text

    async def test_post_decide_approves_via_service(self, client, app):
        prop_repo = app.state.proposal_repo
        proposal = Proposal(id=Proposal.new_id(), project_id="demo", title="t")
        await prop_repo.upsert(proposal)

        r = await client.post(
            f"/projects/demo/proposals/{proposal.id}/decide",
            data={"action": "approve"},
        )
        assert r.status_code == 200
        reloaded = await prop_repo.get(proposal.id)
        assert reloaded.status is ProposalStatus.APPROVED

    async def test_post_decide_rejects_unknown_action(self, client, app):
        prop_repo = app.state.proposal_repo
        proposal = Proposal(id="prop_bad", project_id="demo", title="t")
        await prop_repo.upsert(proposal)
        r = await client.post(
            "/projects/demo/proposals/prop_bad/decide",
            data={"action": "nuke"},
        )
        assert r.status_code == 400

    async def test_inbox_shows_pending_titles(self, client, app):
        prop_repo = app.state.proposal_repo
        await prop_repo.upsert(
            Proposal(id="p1", project_id="demo", title="Visible title"),
        )
        r = await client.get("/projects/demo/proposals")
        assert "Visible title" in r.text

    async def test_portfolio_inbox_lists_pending_by_project(self, client, app):
        # Create a project and a proposal on it
        proj_repo = app.state.project_repo
        from theswarm.domain.projects.entities import Project, ProjectConfig
        from theswarm.domain.projects.value_objects import RepoUrl
        p = Project(id="demo", repo=RepoUrl("demo/demo"), config=ProjectConfig())
        await proj_repo.save(p)
        prop_repo = app.state.proposal_repo
        await prop_repo.upsert(
            Proposal(id="p_a", project_id="demo", title="Inbox item"),
        )
        r = await client.get("/proposals")
        assert r.status_code == 200
        assert "Inbox item" in r.text


class TestPolicyRoutes:
    async def test_get_policy_empty(self, client):
        r = await client.get("/projects/demo/policy")
        assert r.status_code == 200
        assert "Banned" in r.text or "banned" in r.text

    async def test_post_saves_policy(self, client, app):
        r = await client.post(
            "/projects/demo/policy",
            data={
                "title": "P",
                "body_markdown": "no crypto",
                "banned_terms": "crypto, gambling",
                "require_review_terms": "authentication",
            },
        )
        assert r.status_code == 200
        saved = await app.state.policy_repo.get("demo")
        assert saved is not None
        assert "crypto" in saved.banned_terms


class TestOKRRoutes:
    async def test_get_okrs_empty(self, client):
        r = await client.get("/projects/demo/okrs")
        assert r.status_code == 200
        assert "No active OKRs" in r.text

    async def test_create_okr(self, client, app):
        r = await client.post(
            "/projects/demo/okrs",
            data={
                "objective": "Launch v1",
                "quarter": "2026-Q2",
                "owner_codename": "Alice",
                "key_result_1": "ship feature",
                "key_result_2": "hit 100 signups",
            },
        )
        assert r.status_code == 200
        assert "Launch v1" in r.text
        okrs = await app.state.okr_repo.list_for_project("demo")
        assert len(okrs) == 1
        assert len(okrs[0].key_results) == 2

    async def test_retire_okr(self, client, app):
        from theswarm.domain.product.entities import OKR
        await app.state.okr_repo.create(
            OKR(id="okr_r", project_id="demo", objective="x"),
        )
        r = await client.post("/projects/demo/okrs/okr_r/retire")
        assert r.status_code == 200
        active = await app.state.okr_repo.list_for_project("demo")
        assert all(o.id != "okr_r" for o in active)


class TestDigestRoute:
    async def test_empty_digest_shows_placeholder(self, client):
        r = await client.get("/projects/demo/digest")
        assert r.status_code == 200
        assert "No digest generated yet" in r.text

    async def test_generate_now_produces_digest(self, client, app):
        # Seed one signal so the digest has something to aggregate
        await app.state.signal_repo.record(
            Signal(
                id="s1", project_id="demo",
                kind=SignalKind.ECOSYSTEM,
                severity=SignalSeverity.INFO,
                title="trend",
            ),
        )
        r = await client.post("/projects/demo/digest/generate")
        assert r.status_code == 200
        assert "trend" in r.text


class TestSignalsRoute:
    async def test_signals_empty(self, client):
        r = await client.get("/projects/demo/signals")
        assert r.status_code == 200
        assert "No signals" in r.text

    async def test_signals_render(self, client, app):
        await app.state.signal_repo.record(
            Signal(
                id="s2", project_id="demo",
                kind=SignalKind.COMPETITOR,
                severity=SignalSeverity.THREAT,
                title="rival shipped",
            ),
        )
        r = await client.get("/projects/demo/signals")
        assert "rival shipped" in r.text
        assert "threat" in r.text
