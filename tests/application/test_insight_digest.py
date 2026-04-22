"""Tests for InsightDigestService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from theswarm.application.services.insight_digest import InsightDigestService
from theswarm.domain.product.entities import Signal, Proposal
from theswarm.domain.product.value_objects import (
    InsightKind,
    ProposalStatus,
    SignalKind,
    SignalSeverity,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.product import (
    SQLiteDigestRepository,
    SQLiteProposalRepository,
    SQLiteSignalRepository,
)


@pytest.fixture()
async def ctx(tmp_path):
    db = await init_db(str(tmp_path / "digest.db"))
    sig = SQLiteSignalRepository(db)
    prop = SQLiteProposalRepository(db)
    dig = SQLiteDigestRepository(db)
    svc = InsightDigestService(sig, prop, dig)
    yield svc, sig, prop, dig
    await db.close()


class TestDigest:
    async def test_empty_week_produces_quiet_narrative(self, ctx):
        svc, *_ = ctx
        d = await svc.generate(project_id="demo")
        assert "Quiet" in d.narrative
        assert d.items == ()

    async def test_aggregates_signals_and_proposals(self, ctx):
        svc, sig, prop, _ = ctx
        now = datetime.now(timezone.utc)
        await sig.record(
            Signal(
                id="s1", project_id="demo",
                kind=SignalKind.COMPETITOR, severity=SignalSeverity.THREAT,
                title="rival X", body="threat body",
                observed_at=now - timedelta(hours=2),
            ),
        )
        await sig.record(
            Signal(
                id="s2", project_id="demo",
                kind=SignalKind.ECOSYSTEM, severity=SignalSeverity.INFO,
                title="trend Y", body="info body",
                observed_at=now - timedelta(days=2),
            ),
        )
        await prop.upsert(
            Proposal(
                id="p_pending", project_id="demo",
                title="new opportunity", status=ProposalStatus.PROPOSED,
            ),
        )
        d = await svc.generate(project_id="demo", now=now)
        kinds = {item.kind for item in d.items}
        assert InsightKind.RISK in kinds  # s1 → threat → risk
        assert "signals" in d.narrative
        assert "threats" in d.narrative

    async def test_ignores_signals_older_than_one_week(self, ctx):
        svc, sig, _, _ = ctx
        now = datetime.now(timezone.utc)
        await sig.record(
            Signal(
                id="sold", project_id="demo",
                kind=SignalKind.ECOSYSTEM, severity=SignalSeverity.INFO,
                title="old", observed_at=now - timedelta(days=30),
            ),
        )
        d = await svc.generate(project_id="demo", now=now)
        assert not any(i.headline == "old" for i in d.items)

    async def test_digest_is_persisted_and_retrievable(self, ctx):
        svc, sig, _, dig = ctx
        await sig.record(
            Signal(
                id="s1", project_id="demo",
                kind=SignalKind.COMPETITOR,
                severity=SignalSeverity.OPPORTUNITY,
                title="opp", observed_at=datetime.now(timezone.utc),
            ),
        )
        built = await svc.generate(project_id="demo")
        loaded = await dig.latest_for_project("demo")
        assert loaded is not None
        assert loaded.id == built.id
