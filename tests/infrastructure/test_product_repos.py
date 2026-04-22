"""Tests for Phase C SQLite repositories (Proposals, OKRs, Policy, Signal, Digest)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from theswarm.domain.product.entities import (
    DigestItem,
    InsightDigest,
    KeyResult,
    OKR,
    Policy,
    Proposal,
    Signal,
)
from theswarm.domain.product.value_objects import (
    InsightKind,
    ProposalStatus,
    SignalKind,
    SignalSeverity,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.product import (
    SQLiteDigestRepository,
    SQLiteOKRRepository,
    SQLitePolicyRepository,
    SQLiteProposalRepository,
    SQLiteSignalRepository,
)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "prod.db"))
    yield conn
    await conn.close()


# ── Proposals ───────────────────────────────────────────────────────


class TestProposalRepo:
    async def test_upsert_inserts_new_row(self, db):
        repo = SQLiteProposalRepository(db)
        p = Proposal(
            id=Proposal.new_id(),
            project_id="demo",
            title="Add dark mode",
            rationale="users keep asking",
        )
        saved = await repo.upsert(p)
        assert saved.id == p.id
        assert saved.status is ProposalStatus.PROPOSED

    async def test_upsert_is_idempotent_on_dedup_key(self, db):
        repo = SQLiteProposalRepository(db)
        p1 = Proposal(id="prop_1", project_id="demo", title="Ship OAuth")
        p2 = Proposal(id="prop_2", project_id="demo", title="SHIP OAUTH")
        await repo.upsert(p1)
        await repo.upsert(p2)
        items = await repo.list_for_project("demo")
        assert len(items) == 1
        assert items[0].id == "prop_1"

    async def test_decide_updates_status(self, db):
        repo = SQLiteProposalRepository(db)
        p = Proposal(id="prop_x", project_id="demo", title="t")
        await repo.upsert(p)
        updated = await repo.decide(
            "prop_x",
            status=ProposalStatus.APPROVED,
            note="ship it",
            linked_story_id="st_1",
        )
        assert updated is not None
        assert updated.status is ProposalStatus.APPROVED
        assert updated.linked_story_id == "st_1"
        assert updated.decided_at is not None

    async def test_inbox_filters_to_pending(self, db):
        repo = SQLiteProposalRepository(db)
        for i, status in enumerate(
            [
                ProposalStatus.PROPOSED,
                ProposalStatus.APPROVED,
                ProposalStatus.ASKED,
                ProposalStatus.REJECTED,
            ],
        ):
            await repo.upsert(
                Proposal(
                    id=f"prop_{i}",
                    project_id="demo",
                    title=f"t{i}",
                    status=status,
                ),
            )
        inbox = await repo.list_inbox("demo")
        assert {p.status for p in inbox} == {
            ProposalStatus.PROPOSED, ProposalStatus.ASKED,
        }

    async def test_counts_by_status(self, db):
        repo = SQLiteProposalRepository(db)
        for i in range(3):
            await repo.upsert(
                Proposal(id=f"p_{i}", project_id="demo", title=f"t{i}"),
            )
        await repo.decide("p_0", status=ProposalStatus.APPROVED)
        counts = await repo.counts_by_status("demo")
        assert counts.get("approved") == 1
        assert counts.get("proposed") == 2


# ── OKRs ────────────────────────────────────────────────────────────


class TestOKRRepo:
    async def test_create_and_get_with_key_results(self, db):
        repo = SQLiteOKRRepository(db)
        kr = KeyResult(id="kr_1", description="launch v1", target="ship", progress=0.3)
        okr = OKR(
            id="okr_1",
            project_id="demo",
            objective="Launch v1 successfully",
            key_results=(kr,),
            quarter="2026-Q2",
        )
        await repo.create(okr)
        reloaded = await repo.get("okr_1")
        assert reloaded is not None
        assert len(reloaded.key_results) == 1
        assert reloaded.key_results[0].description == "launch v1"

    async def test_update_replaces_key_results(self, db):
        repo = SQLiteOKRRepository(db)
        okr = OKR(
            id="okr_u",
            project_id="demo",
            objective="Base",
            key_results=(
                KeyResult(id="kr_a", description="a"),
                KeyResult(id="kr_b", description="b"),
            ),
        )
        await repo.create(okr)
        from dataclasses import replace
        updated = replace(
            okr,
            objective="New objective",
            key_results=(KeyResult(id="kr_c", description="c"),),
        )
        saved = await repo.update(updated)
        assert saved is not None
        assert saved.objective == "New objective"
        assert [k.description for k in saved.key_results] == ["c"]

    async def test_retire_sets_inactive(self, db):
        repo = SQLiteOKRRepository(db)
        okr = OKR(id="okr_r", project_id="demo", objective="x")
        await repo.create(okr)
        await repo.retire("okr_r")
        active = await repo.list_for_project("demo")
        assert all(o.id != "okr_r" for o in active)
        all_okrs = await repo.list_for_project("demo", active_only=False)
        assert any(o.id == "okr_r" and not o.active for o in all_okrs)

    async def test_update_key_result_progress(self, db):
        repo = SQLiteOKRRepository(db)
        kr = KeyResult(id="kr_p", description="x", progress=0.0)
        okr = OKR(id="okr_p", project_id="demo", objective="obj", key_results=(kr,))
        await repo.create(okr)
        updated = await repo.update_key_result_progress(
            "okr_p", "kr_p", current="42%", progress=0.42,
        )
        assert updated is not None
        assert updated.key_results[0].current == "42%"
        assert updated.key_results[0].progress == pytest.approx(0.42)


# ── Policy ──────────────────────────────────────────────────────────


class TestPolicyRepo:
    async def test_upsert_creates_when_missing(self, db):
        repo = SQLitePolicyRepository(db)
        p = Policy(
            id=Policy.new_id(),
            project_id="demo",
            title="demo policy",
            body_markdown="No crypto.",
            banned_terms=("crypto",),
            require_review_terms=("authentication",),
            updated_by="human",
        )
        saved = await repo.upsert(p)
        assert saved.banned_terms == ("crypto",)
        assert saved.updated_by == "human"

    async def test_upsert_replaces_existing(self, db):
        repo = SQLitePolicyRepository(db)
        p1 = Policy(id="p_1", project_id="demo", banned_terms=("a",))
        p2 = Policy(id="p_2", project_id="demo", banned_terms=("b", "c"))
        await repo.upsert(p1)
        await repo.upsert(p2)
        got = await repo.get("demo")
        assert got is not None
        assert set(got.banned_terms) == {"b", "c"}
        # id is replaced with the latest one
        assert got.id == "p_2"

    async def test_get_returns_none_when_missing(self, db):
        repo = SQLitePolicyRepository(db)
        assert await repo.get("unknown") is None


# ── Signal ──────────────────────────────────────────────────────────


class TestSignalRepo:
    async def test_record_and_list(self, db):
        repo = SQLiteSignalRepository(db)
        s = Signal(
            id=Signal.new_id(),
            project_id="demo",
            kind=SignalKind.COMPETITOR,
            severity=SignalSeverity.THREAT,
            title="rival shipped X",
        )
        await repo.record(s)
        items = await repo.list_for_project("demo")
        assert len(items) == 1
        assert items[0].title == "rival shipped X"

    async def test_filter_by_kind(self, db):
        repo = SQLiteSignalRepository(db)
        await repo.record(
            Signal(
                id="sa", project_id="demo",
                kind=SignalKind.COMPETITOR, severity=SignalSeverity.THREAT,
                title="comp",
            ),
        )
        await repo.record(
            Signal(
                id="sb", project_id="demo",
                kind=SignalKind.ECOSYSTEM, severity=SignalSeverity.INFO,
                title="eco",
            ),
        )
        only_comp = await repo.list_for_project(
            "demo", kinds=(SignalKind.COMPETITOR,),
        )
        assert [s.id for s in only_comp] == ["sa"]

    async def test_since_filter(self, db):
        repo = SQLiteSignalRepository(db)
        old = datetime(2026, 1, 1, tzinfo=timezone.utc)
        new = datetime(2026, 4, 20, tzinfo=timezone.utc)
        await repo.record(
            Signal(id="old", project_id="demo", kind=SignalKind.ECOSYSTEM,
                   severity=SignalSeverity.INFO, title="old", observed_at=old),
        )
        await repo.record(
            Signal(id="new", project_id="demo", kind=SignalKind.ECOSYSTEM,
                   severity=SignalSeverity.INFO, title="new", observed_at=new),
        )
        cutoff = datetime(2026, 3, 1, tzinfo=timezone.utc)
        recent = await repo.list_for_project("demo", since=cutoff)
        assert [s.id for s in recent] == ["new"]


# ── Digest ──────────────────────────────────────────────────────────


class TestDigestRepo:
    async def test_save_and_retrieve_latest(self, db):
        repo = SQLiteDigestRepository(db)
        d = InsightDigest(
            id=InsightDigest.new_id(),
            project_id="demo",
            week_start=datetime(2026, 4, 20, tzinfo=timezone.utc),
            items=(
                DigestItem(kind=InsightKind.TREND, headline="LLMs cheaper"),
                DigestItem(kind=InsightKind.COMPETITOR_MOVE, headline="Rival X"),
            ),
            narrative="big week",
        )
        await repo.save(d)
        latest = await repo.latest_for_project("demo")
        assert latest is not None
        assert len(latest.items) == 2
        assert latest.narrative == "big week"

    async def test_list_for_project_newest_first(self, db):
        repo = SQLiteDigestRepository(db)
        for n in range(3):
            ws = datetime(2026, 4, 1 + n * 7, tzinfo=timezone.utc)
            await repo.save(
                InsightDigest(
                    id=f"dig_{n}", project_id="demo", week_start=ws,
                ),
            )
        items = await repo.list_for_project("demo")
        assert items[0].id == "dig_2"
