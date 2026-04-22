"""Phase E infrastructure tests for Dev-rigour SQLite repositories."""

from __future__ import annotations

import pytest

from theswarm.domain.dev_rigour.entities import (
    CoverageDelta,
    DevThought,
    RefactorPreflight,
    SelfReview,
    SelfReviewFinding,
    TddArtifact,
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
    conn = await init_db(str(tmp_path / "dev_rigour.db"))
    yield conn
    await conn.close()


class TestDevThoughtRepo:
    async def test_add_and_list(self, db):
        repo = SQLiteDevThoughtRepository(db)
        await repo.add(DevThought(
            id="t1", project_id="p1", kind=ThoughtKind.EXPLORE,
            content="grepped auth/*",
        ))
        await repo.add(DevThought(
            id="t2", project_id="p1", kind=ThoughtKind.REUSE,
            content="found helpers.time",
        ))
        await repo.add(DevThought(
            id="t3", project_id="p2", kind=ThoughtKind.NOTE,
            content="other project",
        ))

        listed = await repo.list_for_project("p1")
        assert len(listed) == 2
        assert listed[0].kind == ThoughtKind.REUSE  # newest first

    async def test_list_for_task(self, db):
        repo = SQLiteDevThoughtRepository(db)
        await repo.add(DevThought(id="a", project_id="p", task_id="task-1"))
        await repo.add(DevThought(id="b", project_id="p", task_id="task-1"))
        await repo.add(DevThought(id="c", project_id="p", task_id="task-2"))

        rows = await repo.list_for_task("task-1")
        assert len(rows) == 2


class TestTddArtifactRepo:
    async def test_upsert_creates_then_updates(self, db):
        repo = SQLiteTddArtifactRepository(db)
        a = TddArtifact(
            id="tdd_1",
            project_id="p",
            task_id="T1",
            phase=TddPhase.RED,
            test_files=("tests/test_foo.py",),
            red_commit="abc123",
        )
        await repo.upsert(a)

        # promote to GREEN
        a2 = TddArtifact(
            id="tdd_1",
            project_id="p",
            task_id="T1",
            phase=TddPhase.GREEN,
            test_files=("tests/test_foo.py",),
            red_commit="abc123",
            green_commit="def456",
        )
        await repo.upsert(a2)

        got = await repo.get_for_task("p", "T1")
        assert got is not None
        assert got.phase == TddPhase.GREEN
        assert got.green_commit == "def456"

    async def test_list_for_project(self, db):
        repo = SQLiteTddArtifactRepository(db)
        await repo.upsert(TddArtifact(id="a", project_id="p", task_id="T1"))
        await repo.upsert(TddArtifact(id="b", project_id="p", task_id="T2"))
        await repo.upsert(TddArtifact(id="c", project_id="q", task_id="T3"))

        listed = await repo.list_for_project("p")
        assert len(listed) == 2


class TestRefactorPreflightRepo:
    async def test_add_and_list(self, db):
        repo = SQLiteRefactorPreflightRepository(db)
        await repo.add(RefactorPreflight(
            id="r1", project_id="p",
            deletion_lines=35,
            files_touched=("src/legacy.py",),
            callers_checked=("app.py", "cli.py"),
            decision=PreflightDecision.PROCEED,
        ))
        await repo.add(RefactorPreflight(
            id="r2", project_id="p",
            deletion_lines=120,
            decision=PreflightDecision.BAIL,
            reason="unclear callers in dynamic dispatch",
        ))

        listed = await repo.list_for_project("p")
        assert len(listed) == 2
        assert listed[0].decision == PreflightDecision.BAIL
        assert listed[0].reason.startswith("unclear")
        assert listed[1].callers_checked == ("app.py", "cli.py")


class TestSelfReviewRepo:
    async def test_round_trip_findings(self, db):
        repo = SQLiteSelfReviewRepository(db)
        r = SelfReview(
            id="sr1",
            project_id="p",
            pr_url="http://pr/1",
            findings=(
                SelfReviewFinding(
                    severity=FindingSeverity.HIGH,
                    category="duplication",
                    message="duplicates helper.foo",
                ),
                SelfReviewFinding(
                    severity=FindingSeverity.LOW,
                    category="naming",
                    waived=True,
                    waive_reason="intentional abbreviation",
                ),
            ),
            summary="mostly OK",
        )
        await repo.add(r)

        got = await repo.list_for_project("p")
        assert len(got) == 1
        fetched = got[0]
        assert fetched.high_count == 1
        assert fetched.waived_count == 1
        assert fetched.findings[0].category == "duplication"
        assert fetched.findings[1].waive_reason == "intentional abbreviation"


class TestCoverageDeltaRepo:
    async def test_add_list_and_latest_for_pr(self, db):
        repo = SQLiteCoverageDeltaRepository(db)
        await repo.add(CoverageDelta(
            id="c1", project_id="p", pr_url="http://pr/1",
            total_before_pct=80.0, total_after_pct=82.5,
            changed_lines_pct=88.0, changed_lines=40, missed_lines=5,
        ))
        await repo.add(CoverageDelta(
            id="c2", project_id="p", pr_url="http://pr/2",
            total_before_pct=82.5, total_after_pct=78.0,
            changed_lines_pct=55.0, changed_lines=30, missed_lines=14,
        ))

        listed = await repo.list_for_project("p")
        assert len(listed) == 2
        latest_pr1 = await repo.latest_for_pr("http://pr/1")
        assert latest_pr1 is not None
        assert latest_pr1.delta == 2.5
        assert latest_pr1.passes_threshold is True

        latest_pr2 = await repo.latest_for_pr("http://pr/2")
        assert latest_pr2 is not None
        assert latest_pr2.passes_threshold is False

    async def test_latest_for_pr_missing(self, db):
        repo = SQLiteCoverageDeltaRepository(db)
        assert await repo.latest_for_pr("http://pr/missing") is None
