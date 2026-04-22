"""Tests for TechLead application services."""

from __future__ import annotations

import pytest

from theswarm.application.services.adr_service import ADRService
from theswarm.application.services.debt_service import DebtService
from theswarm.application.services.dependency_radar import DependencyRadar
from theswarm.application.services.review_calibration import (
    ReviewCalibrationService,
)
from theswarm.application.services.second_opinion import SecondOpinionService
from theswarm.domain.techlead.value_objects import (
    ADRStatus,
    DebtSeverity,
    DepSeverity,
    ReviewDecision,
    ReviewOutcome,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.techlead import (
    SQLiteADRRepository,
    SQLiteCriticalPathRepository,
    SQLiteDebtRepository,
    SQLiteDepFindingRepository,
    SQLiteReviewVerdictRepository,
)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "tl_svc.db"))
    yield conn
    await conn.close()


# ── ADRService ─────────────────────────────────────────────────────


class TestADRService:
    async def test_propose_assigns_number(self, db):
        svc = ADRService(SQLiteADRRepository(db))
        a1 = await svc.propose(project_id="demo", title="First")
        a2 = await svc.propose(project_id="demo", title="Second")
        assert a1.number == 1
        assert a2.number == 2
        assert a1.status is ADRStatus.PROPOSED

    async def test_accept_and_reject(self, db):
        svc = ADRService(SQLiteADRRepository(db))
        a = await svc.propose(project_id="demo", title="t")
        accepted = await svc.accept(a.id)
        assert accepted is not None and accepted.status is ADRStatus.ACCEPTED

    async def test_supersede_marks_old_superseded(self, db):
        svc = ADRService(SQLiteADRRepository(db))
        old = await svc.propose(project_id="demo", title="old")
        new = await svc.propose(project_id="demo", title="new")
        old_now = await svc.supersede(old.id, new.id)
        assert old_now is not None and old_now.status is ADRStatus.SUPERSEDED


# ── DebtService ────────────────────────────────────────────────────


class TestDebtService:
    async def test_add_and_list(self, db):
        svc = DebtService(SQLiteDebtRepository(db))
        await svc.add(project_id="demo", title="legacy", severity=DebtSeverity.HIGH)
        items = await svc.list("demo")
        assert len(items) == 1
        assert items[0].title == "legacy"

    async def test_resolve_hides_from_default_list(self, db):
        svc = DebtService(SQLiteDebtRepository(db))
        d = await svc.add(project_id="demo", title="t")
        await svc.resolve(d.id)
        assert await svc.list("demo") == []
        assert len(await svc.list("demo", include_resolved=True)) == 1


# ── DependencyRadar ────────────────────────────────────────────────


class _FakeProjects:
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    async def list_all(self) -> list:
        class P:
            def __init__(self, i: str) -> None:
                self.id = i
        return [P(i) for i in self._ids]


class TestDependencyRadar:
    async def test_scan_persists_new_findings(self, db):
        projects = _FakeProjects(["demo"])
        deps = SQLiteDepFindingRepository(db)

        async def fake_scanner(pid: str) -> list[dict]:
            return [
                {
                    "package": "requests",
                    "installed_version": "2.30.0",
                    "advisory_id": "CVE-2024-1",
                    "severity": DepSeverity.HIGH.value,
                    "summary": "SSRF risk",
                    "fixed_version": "2.32.0",
                    "source": "pip-audit",
                    "url": "https://example/CVE-2024-1",
                },
            ]

        radar = DependencyRadar(
            projects, deps, scanners={"pip-audit": fake_scanner},
        )
        reports = await radar.run_all()
        assert len(reports) == 1
        assert reports[0].findings_new == 1
        items = await deps.list_for_project("demo")
        assert len(items) == 1
        assert items[0].package == "requests"
        assert items[0].severity is DepSeverity.HIGH

    async def test_rerun_refreshes_not_duplicates(self, db):
        projects = _FakeProjects(["demo"])
        deps = SQLiteDepFindingRepository(db)
        calls: list[DepSeverity] = [DepSeverity.MEDIUM, DepSeverity.CRITICAL]

        async def fake_scanner(pid: str) -> list[dict]:
            sev = calls.pop(0)
            return [{
                "package": "lib",
                "advisory_id": "GHSA-x",
                "severity": sev.value,
                "summary": "sx",
            }]

        radar = DependencyRadar(projects, deps, scanners={"osv": fake_scanner})
        await radar.run_all()
        await radar.run_all()
        items = await deps.list_for_project("demo")
        assert len(items) == 1
        assert items[0].severity is DepSeverity.CRITICAL

    async def test_missing_package_is_skipped(self, db):
        projects = _FakeProjects(["demo"])
        deps = SQLiteDepFindingRepository(db)

        async def fake_scanner(pid: str) -> list[dict]:
            return [{"advisory_id": "x"}]  # no package

        radar = DependencyRadar(projects, deps, scanners={"s": fake_scanner})
        reports = await radar.run_all()
        assert reports[0].findings_new == 0


# ── ReviewCalibrationService ───────────────────────────────────────


class TestReviewCalibration:
    async def test_stats_empty(self, db):
        svc = ReviewCalibrationService(SQLiteReviewVerdictRepository(db))
        stats = await svc.stats("demo")
        assert stats.total == 0
        assert stats.signed is False
        assert stats.false_positive_rate == 0.0
        assert stats.false_negative_rate == 0.0

    async def test_fn_rate_when_approve_reverted(self, db):
        repo = SQLiteReviewVerdictRepository(db)
        svc = ReviewCalibrationService(repo)
        v = await svc.record(
            project_id="demo",
            pr_url="u",
            reviewer_codename="Marcus",
            decision=ReviewDecision.APPROVE,
        )
        await svc.set_outcome(v.id, ReviewOutcome.REVERTED)
        stats = await svc.stats("demo")
        assert stats.approved == 1
        assert stats.reverted == 1
        assert stats.false_negative_rate == 1.0

    async def test_fp_rate_when_changes_requested_but_clean_after_override(self, db):
        repo = SQLiteReviewVerdictRepository(db)
        svc = ReviewCalibrationService(repo)
        v = await svc.record(
            project_id="demo",
            pr_url="u",
            reviewer_codename="Marcus",
            decision=ReviewDecision.REQUEST_CHANGES,
            override_reason="pragmatic approve",
        )
        await svc.set_outcome(v.id, ReviewOutcome.CLEAN)
        stats = await svc.stats("demo")
        assert stats.requested_changes == 1
        assert stats.false_positive_rate == 1.0


# ── SecondOpinionService ───────────────────────────────────────────


class TestSecondOpinion:
    async def test_no_paths_registered_means_not_required(self, db):
        svc = SecondOpinionService(SQLiteCriticalPathRepository(db))
        decision = await svc.evaluate("demo", ("src/app.py",))
        assert decision.required is False

    async def test_match_triggers_required(self, db):
        svc = SecondOpinionService(SQLiteCriticalPathRepository(db))
        await svc.add_critical_path("demo", "auth", reason="PII handling")
        decision = await svc.evaluate(
            "demo", ("src/auth/token.py", "README.md"),
        )
        assert decision.required is True
        assert "auth" in decision.matched_patterns
        assert "PII handling" in decision.reason

    async def test_no_match(self, db):
        svc = SecondOpinionService(SQLiteCriticalPathRepository(db))
        await svc.add_critical_path("demo", "db/*")
        decision = await svc.evaluate("demo", ("src/ui.py",))
        assert decision.required is False
