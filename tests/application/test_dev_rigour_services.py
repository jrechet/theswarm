"""Phase E application-layer tests for Dev-rigour services."""

from __future__ import annotations

import pytest

from theswarm.application.services.dev_rigour import (
    CoverageDeltaService,
    DevThoughtService,
    RefactorPreflightService,
    SelfReviewService,
    TddGateService,
)
from theswarm.domain.dev_rigour.value_objects import (
    FindingSeverity,
    PreflightDecision,
    TddPhase,
    ThoughtKind,
)
from theswarm.infrastructure.dev_rigour import (
    SQLiteCoverageDeltaRepository,
    SQLiteDevThoughtRepository,
    SQLiteRefactorPreflightRepository,
    SQLiteSelfReviewRepository,
    SQLiteTddArtifactRepository,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "svc.db"))
    yield conn
    await conn.close()


class TestDevThoughtService:
    async def test_log_and_recent(self, db):
        svc = DevThoughtService(SQLiteDevThoughtRepository(db))
        await svc.log(project_id="p", kind=ThoughtKind.EXPLORE, content="a")
        await svc.log(project_id="p", kind=ThoughtKind.REUSE, content="b")
        recent = await svc.recent("p")
        assert len(recent) == 2
        assert recent[0].kind == ThoughtKind.REUSE

    async def test_content_is_stripped(self, db):
        svc = DevThoughtService(SQLiteDevThoughtRepository(db))
        t = await svc.log(project_id="p", content="   hello  \n")
        assert t.content == "hello"

    async def test_for_task_scopes(self, db):
        svc = DevThoughtService(SQLiteDevThoughtRepository(db))
        await svc.log(project_id="p", task_id="T1", content="x")
        await svc.log(project_id="p", task_id="T2", content="y")
        rows = await svc.for_task("T1")
        assert len(rows) == 1


class TestTddGateService:
    async def test_red_then_green(self, db):
        svc = TddGateService(SQLiteTddArtifactRepository(db))
        red = await svc.record_red(
            project_id="p", task_id="T1",
            test_files=("tests/t.py",), commit="abc",
        )
        assert red.phase == TddPhase.RED

        green = await svc.record_green(
            project_id="p", task_id="T1", commit="def",
        )
        assert green is not None
        assert green.phase == TddPhase.GREEN
        assert green.green_commit == "def"
        # red commit preserved
        assert green.red_commit == "abc"

    async def test_green_before_red_returns_none(self, db):
        svc = TddGateService(SQLiteTddArtifactRepository(db))
        out = await svc.record_green(project_id="p", task_id="X")
        assert out is None

    async def test_refactor_requires_green(self, db):
        svc = TddGateService(SQLiteTddArtifactRepository(db))
        await svc.record_red(project_id="p", task_id="T")
        # still RED — refactor rejected
        assert await svc.mark_refactor(project_id="p", task_id="T") is None

        await svc.record_green(project_id="p", task_id="T")
        ref = await svc.mark_refactor(project_id="p", task_id="T")
        assert ref is not None
        assert ref.phase == TddPhase.REFACTOR

    async def test_list_recent_first(self, db):
        svc = TddGateService(SQLiteTddArtifactRepository(db))
        await svc.record_red(project_id="p", task_id="A")
        await svc.record_red(project_id="p", task_id="B")
        items = await svc.list("p")
        assert {i.task_id for i in items} == {"A", "B"}


class TestRefactorPreflightService:
    async def test_below_threshold_skips(self, db):
        svc = RefactorPreflightService(
            SQLiteRefactorPreflightRepository(db), threshold_lines=20,
        )
        out = await svc.evaluate(project_id="p", deletion_lines=5)
        assert out is None

    async def test_at_or_above_threshold_records(self, db):
        svc = RefactorPreflightService(
            SQLiteRefactorPreflightRepository(db), threshold_lines=20,
        )
        out = await svc.evaluate(
            project_id="p",
            deletion_lines=25,
            files_touched=("a.py",),
            decision=PreflightDecision.BAIL,
            reason="too risky",
        )
        assert out is not None
        assert out.decision == PreflightDecision.BAIL

        listed = await svc.list("p")
        assert len(listed) == 1

    async def test_threshold_accessor(self, db):
        svc = RefactorPreflightService(
            SQLiteRefactorPreflightRepository(db), threshold_lines=50,
        )
        assert svc.threshold_lines == 50


class TestSelfReviewService:
    async def test_record_with_findings(self, db):
        svc = SelfReviewService(SQLiteSelfReviewRepository(db))
        f1 = svc.make_finding(
            severity=FindingSeverity.HIGH,
            category="duplication",
            message="copy of helpers.bar",
        )
        f2 = svc.make_finding(
            severity=FindingSeverity.MEDIUM,
            category="naming",
            waived=True,
            waive_reason="legacy identifier",
        )
        r = await svc.record(
            project_id="p", pr_url="http://pr/1",
            findings=(f1, f2), summary="mostly green",
        )
        assert r.high_count == 1
        assert svc.count_high(r) == 1
        assert r.waived_count == 1

    async def test_list_empty(self, db):
        svc = SelfReviewService(SQLiteSelfReviewRepository(db))
        assert await svc.list("p") == []


class TestCoverageDeltaService:
    async def test_record_and_latest(self, db):
        svc = CoverageDeltaService(SQLiteCoverageDeltaRepository(db))
        await svc.record(
            project_id="p", pr_url="http://pr/1",
            total_before_pct=78.0, total_after_pct=82.0,
            changed_lines_pct=85.0, changed_lines=50, missed_lines=7,
        )
        latest = await svc.latest_for_pr("http://pr/1")
        assert latest is not None
        assert latest.delta == 4.0
        assert latest.passes_threshold is True

    async def test_threshold_default_80(self, db):
        svc = CoverageDeltaService(SQLiteCoverageDeltaRepository(db))
        out = await svc.record(
            project_id="p", changed_lines_pct=70.0,
        )
        assert out.threshold_pct == 80.0
        assert out.passes_threshold is False

    async def test_threshold_override(self, db):
        svc = CoverageDeltaService(
            SQLiteCoverageDeltaRepository(db), default_threshold_pct=70.0,
        )
        out = await svc.record(
            project_id="p", changed_lines_pct=70.0,
        )
        assert out.threshold_pct == 70.0
        assert out.passes_threshold is True
