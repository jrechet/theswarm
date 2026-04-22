"""Tests for TechLead SQLite repositories."""

from __future__ import annotations

import pytest

from theswarm.domain.techlead.entities import (
    ADR,
    CriticalPath,
    DebtEntry,
    DepFinding,
    ReviewVerdict,
)
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
    conn = await init_db(str(tmp_path / "tl.db"))
    yield conn
    await conn.close()


# ── ADR ────────────────────────────────────────────────────────────


class TestADRRepo:
    async def test_next_number_starts_at_one(self, db):
        repo = SQLiteADRRepository(db)
        n = await repo.next_number("demo")
        assert n == 1

    async def test_create_and_get(self, db):
        repo = SQLiteADRRepository(db)
        adr = ADR(
            id=ADR.new_id(),
            project_id="demo",
            number=1,
            title="Adopt Event Bus",
            status=ADRStatus.ACCEPTED,
            decision="Use in-process EventBus.",
        )
        await repo.create(adr)
        got = await repo.get(adr.id)
        assert got is not None
        assert got.title == "Adopt Event Bus"
        assert got.status is ADRStatus.ACCEPTED

    async def test_numbering_increments(self, db):
        repo = SQLiteADRRepository(db)
        await repo.create(ADR(id="a1", project_id="demo", number=1, title="t1"))
        await repo.create(ADR(id="a2", project_id="demo", number=2, title="t2"))
        assert await repo.next_number("demo") == 3

    async def test_list_orders_by_number_desc(self, db):
        repo = SQLiteADRRepository(db)
        await repo.create(ADR(id="a1", project_id="demo", number=1, title="t1"))
        await repo.create(ADR(id="a2", project_id="demo", number=2, title="t2"))
        items = await repo.list_for_project("demo")
        assert [a.number for a in items] == [2, 1]

    async def test_set_status(self, db):
        repo = SQLiteADRRepository(db)
        await repo.create(ADR(id="a1", project_id="demo", number=1, title="t"))
        got = await repo.set_status("a1", ADRStatus.SUPERSEDED)
        assert got is not None
        assert got.status is ADRStatus.SUPERSEDED


# ── Debt ───────────────────────────────────────────────────────────


class TestDebtRepo:
    async def test_create_and_list_excludes_resolved(self, db):
        repo = SQLiteDebtRepository(db)
        await repo.create(
            DebtEntry(id="d1", project_id="demo", title="legacy", severity=DebtSeverity.HIGH),
        )
        r = DebtEntry(id="d2", project_id="demo", title="done", resolved=True)
        await repo.create(r)
        items = await repo.list_for_project("demo")
        assert [d.id for d in items] == ["d1"]

    async def test_resolve(self, db):
        repo = SQLiteDebtRepository(db)
        await repo.create(DebtEntry(id="d1", project_id="demo", title="t"))
        got = await repo.resolve("d1")
        assert got is not None
        assert got.resolved is True
        assert got.resolved_at is not None

    async def test_list_sorts_by_severity(self, db):
        repo = SQLiteDebtRepository(db)
        await repo.create(DebtEntry(id="d_low", project_id="demo", title="low", severity=DebtSeverity.LOW))
        await repo.create(DebtEntry(id="d_crit", project_id="demo", title="c", severity=DebtSeverity.CRITICAL))
        await repo.create(DebtEntry(id="d_hi", project_id="demo", title="h", severity=DebtSeverity.HIGH))
        items = await repo.list_for_project("demo")
        assert [d.id for d in items] == ["d_crit", "d_hi", "d_low"]


# ── Dep findings ───────────────────────────────────────────────────


class TestDepFindingRepo:
    async def test_upsert_is_dedupe(self, db):
        repo = SQLiteDepFindingRepository(db)
        f1 = DepFinding(
            id="f1", project_id="demo", package="requests",
            advisory_id="CVE-1", severity=DepSeverity.HIGH, summary="s1",
        )
        f2 = DepFinding(
            id="f2", project_id="demo", package="requests",
            advisory_id="CVE-1", severity=DepSeverity.CRITICAL, summary="s2",
        )
        await repo.upsert(f1)
        await repo.upsert(f2)
        items = await repo.list_for_project("demo")
        assert len(items) == 1
        # Existing row keeps original id but gets refreshed severity/summary
        assert items[0].id == "f1"
        assert items[0].severity is DepSeverity.CRITICAL
        assert items[0].summary == "s2"

    async def test_list_excludes_dismissed(self, db):
        repo = SQLiteDepFindingRepository(db)
        await repo.upsert(DepFinding(id="f1", project_id="demo", package="a", advisory_id="A"))
        await repo.upsert(DepFinding(id="f2", project_id="demo", package="b", advisory_id="B"))
        await repo.dismiss("f1")
        items = await repo.list_for_project("demo")
        assert [f.id for f in items] == ["f2"]


# ── Review verdicts ────────────────────────────────────────────────


class TestVerdictRepo:
    async def test_record_and_set_outcome(self, db):
        repo = SQLiteReviewVerdictRepository(db)
        v = ReviewVerdict(
            id="v1", project_id="demo", pr_url="http://pr/1",
            reviewer_codename="Marcus", decision=ReviewDecision.APPROVE,
        )
        await repo.record(v)
        got = await repo.set_outcome("v1", ReviewOutcome.REVERTED, note="rolled back")
        assert got is not None
        assert got.outcome is ReviewOutcome.REVERTED
        assert got.outcome_note == "rolled back"

    async def test_list_for_project(self, db):
        repo = SQLiteReviewVerdictRepository(db)
        await repo.record(ReviewVerdict(id="v1", project_id="demo", pr_url="u"))
        await repo.record(ReviewVerdict(id="v2", project_id="demo", pr_url="u"))
        items = await repo.list_for_project("demo")
        assert len(items) == 2


# ── Critical paths ─────────────────────────────────────────────────


class TestCriticalPathRepo:
    async def test_add_and_list(self, db):
        repo = SQLiteCriticalPathRepository(db)
        await repo.add(CriticalPath(id="c1", project_id="demo", pattern="auth/*"))
        items = await repo.list_for_project("demo")
        assert len(items) == 1
        assert items[0].pattern == "auth/*"

    async def test_delete(self, db):
        repo = SQLiteCriticalPathRepository(db)
        await repo.add(CriticalPath(id="c1", project_id="demo", pattern="x"))
        await repo.delete("c1")
        assert await repo.list_for_project("demo") == []
