"""Phase J application tests — Analyst services."""

from __future__ import annotations

import pytest

from theswarm.application.services.analyst import (
    InstrumentationPlanService,
    MetricDefinitionService,
    OutcomeObservationService,
)
from theswarm.domain.analyst.value_objects import (
    InstrumentationStatus,
    MetricKind,
    OutcomeDirection,
)
from theswarm.infrastructure.analyst import (
    SQLiteInstrumentationPlanRepository,
    SQLiteMetricDefinitionRepository,
    SQLiteOutcomeObservationRepository,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "analyst_svc.db"))
    yield conn
    await conn.close()


class TestMetricDefinitionService:
    async def test_upsert_preserves_id_on_update(self, db):
        svc = MetricDefinitionService(SQLiteMetricDefinitionRepository(db))
        m1 = await svc.upsert(
            "p", name="conv", kind=MetricKind.RATIO, unit="%",
        )
        m2 = await svc.upsert(
            "p", name="conv", kind=MetricKind.RATIO, unit="%",
            target=">25%",
        )
        assert m1.id == m2.id
        assert m2.target == ">25%"


class TestInstrumentationPlanService:
    async def test_upsert_and_mark_verified(self, db):
        svc = InstrumentationPlanService(
            SQLiteInstrumentationPlanRepository(db),
        )
        p = await svc.upsert(
            "p", story_id="S1", metric_name="conv",
            hypothesis="expect +5pp",
        )
        assert p.status == InstrumentationStatus.PROPOSED

        updated = await svc.mark_status(
            "p", "S1", "conv",
            status=InstrumentationStatus.VERIFIED, note="looks good",
        )
        assert updated.status == InstrumentationStatus.VERIFIED
        assert updated.note == "looks good"

    async def test_missing_only_filter(self, db):
        svc = InstrumentationPlanService(
            SQLiteInstrumentationPlanRepository(db),
        )
        await svc.upsert(
            "p", story_id="S1", metric_name="conv",
            status=InstrumentationStatus.VERIFIED,
        )
        await svc.upsert(
            "p", story_id="S2", metric_name="conv",
            status=InstrumentationStatus.MISSING,
        )
        all_ = await svc.list("p")
        assert len(all_) == 2
        missing = await svc.list("p", missing_only=True)
        assert len(missing) == 1

    async def test_mark_status_missing_raises(self, db):
        svc = InstrumentationPlanService(
            SQLiteInstrumentationPlanRepository(db),
        )
        with pytest.raises(ValueError):
            await svc.mark_status(
                "p", "no", "no",
                status=InstrumentationStatus.VERIFIED,
            )


class TestOutcomeObservationService:
    async def test_record_and_list(self, db):
        svc = OutcomeObservationService(
            SQLiteOutcomeObservationRepository(db),
        )
        o = await svc.record(
            "p", story_id="S1", metric_name="conv",
            baseline="18%", observed="22%",
            direction=OutcomeDirection.IMPROVED, window="7d",
        )
        assert o.is_positive
        rows = await svc.list("p")
        assert len(rows) == 1
        for_story = await svc.list_for_story("p", "S1")
        assert len(for_story) == 1
