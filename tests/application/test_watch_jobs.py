"""Tests for WatchRunner (scheduled PO watch jobs)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from theswarm.application.services.policy_filter import PolicyFilter
from theswarm.application.services.proposal_service import ProposalService
from theswarm.application.services.watch_jobs import WatchRunner
from theswarm.domain.product.value_objects import SignalKind
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.product import (
    SQLitePolicyRepository,
    SQLiteProposalRepository,
    SQLiteSignalRepository,
)


@dataclass
class _FakeProject:
    id: str


class _FakeProjectRepo:
    def __init__(self, ids):
        self._projects = [_FakeProject(id=i) for i in ids]

    async def list_active(self):
        return list(self._projects)


@pytest.fixture()
async def services(tmp_path):
    db = await init_db(str(tmp_path / "watch.db"))
    prop_repo = SQLiteProposalRepository(db)
    pol_repo = SQLitePolicyRepository(db)
    sig_repo = SQLiteSignalRepository(db)
    pf = PolicyFilter(pol_repo)
    svc = ProposalService(prop_repo, pf, signal_repo=sig_repo)
    yield svc, prop_repo, sig_repo
    await db.close()


class TestWatchRunner:
    async def test_no_source_returns_empty(self, services):
        svc, *_ = services
        runner = WatchRunner(
            _FakeProjectRepo([]), svc,
            competitor_source=None, ecosystem_source=None,
        )
        assert await runner.run_competitor_watch() == []
        assert await runner.run_ecosystem_watch() == []

    async def test_competitor_source_creates_proposals(self, services):
        svc, prop_repo, sig_repo = services

        async def competitor(pid: str):
            return [
                {
                    "title": f"rival shipped X in {pid}",
                    "body": "full body",
                    "source_url": "https://rival/a",
                    "severity": "threat",
                    "confidence": 0.8,
                },
            ]

        runner = WatchRunner(
            _FakeProjectRepo(["demo"]), svc,
            competitor_source=competitor,
        )
        reports = await runner.run_competitor_watch()
        assert len(reports) == 1
        assert reports[0].signals_created == 1
        assert reports[0].proposals_created == 1
        sigs = await sig_repo.list_for_project("demo")
        assert sigs[0].kind is SignalKind.COMPETITOR
        proposals = await prop_repo.list_for_project("demo")
        assert len(proposals) == 1
        assert "rival" in proposals[0].title

    async def test_low_confidence_info_signals_skipped(self, services):
        svc, prop_repo, _ = services

        async def ecosystem(pid: str):
            return [
                {"title": "maybe", "confidence": 0.2, "severity": "info"},
                {"title": "strong", "confidence": 0.9, "severity": "info"},
            ]

        runner = WatchRunner(
            _FakeProjectRepo(["demo"]), svc, ecosystem_source=ecosystem,
        )
        reports = await runner.run_ecosystem_watch()
        assert reports[0].proposals_created == 1
        props = await prop_repo.list_for_project("demo")
        assert [p.title for p in props] == ["strong"]

    async def test_threats_bypass_confidence_floor(self, services):
        svc, prop_repo, _ = services

        async def competitor(pid: str):
            return [
                {"title": "T", "confidence": 0.1, "severity": "threat"},
            ]

        runner = WatchRunner(
            _FakeProjectRepo(["demo"]), svc, competitor_source=competitor,
        )
        reports = await runner.run_competitor_watch()
        assert reports[0].proposals_created == 1

    async def test_multiple_projects_scanned_independently(self, services):
        svc, prop_repo, _ = services

        async def src(pid: str):
            return [{"title": f"t-{pid}", "confidence": 0.9, "severity": "info"}]

        runner = WatchRunner(
            _FakeProjectRepo(["a", "b"]), svc, ecosystem_source=src,
        )
        reports = await runner.run_ecosystem_watch()
        pids = {r.project_id for r in reports}
        assert pids == {"a", "b"}
        titles_a = {p.title for p in await prop_repo.list_for_project("a")}
        titles_b = {p.title for p in await prop_repo.list_for_project("b")}
        assert titles_a == {"t-a"}
        assert titles_b == {"t-b"}
