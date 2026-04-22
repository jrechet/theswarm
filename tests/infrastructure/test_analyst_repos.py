"""Phase J infrastructure tests — Analyst repos."""

from __future__ import annotations

import pytest

from theswarm.domain.analyst.entities import (
    InstrumentationPlan,
    MetricDefinition,
    OutcomeObservation,
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
    conn = await init_db(str(tmp_path / "analyst.db"))
    yield conn
    await conn.close()


class TestMetricDefinitionRepo:
    async def test_upsert_preserves_id(self, db):
        repo = SQLiteMetricDefinitionRepository(db)
        m1 = MetricDefinition(
            id="m1", project_id="p", name="conv",
            kind=MetricKind.RATIO, unit="%",
        )
        got1 = await repo.upsert(m1)
        m2 = MetricDefinition(
            id="m2", project_id="p", name="conv",
            kind=MetricKind.RATIO, unit="%", target=">20%",
        )
        got2 = await repo.upsert(m2)
        # same composite key → keeps m1's id
        assert got2.id == got1.id
        assert got2.target == ">20%"

        listed = await repo.list_for_project("p")
        assert len(listed) == 1


class TestInstrumentationPlanRepo:
    async def test_upsert_and_list_missing_only(self, db):
        repo = SQLiteInstrumentationPlanRepository(db)
        a = InstrumentationPlan(
            id="a", project_id="p", story_id="S1", metric_name="conv",
            status=InstrumentationStatus.VERIFIED,
        )
        b = InstrumentationPlan(
            id="b", project_id="p", story_id="S2", metric_name="conv",
            status=InstrumentationStatus.MISSING,
        )
        await repo.upsert(a)
        await repo.upsert(b)

        all_ = await repo.list_for_project("p")
        assert len(all_) == 2

        missing = await repo.list_for_project("p", missing_only=True)
        assert len(missing) == 1
        assert missing[0].story_id == "S2"


class TestOutcomeObservationRepo:
    async def test_add_and_list(self, db):
        repo = SQLiteOutcomeObservationRepository(db)
        o = OutcomeObservation(
            id="o1", project_id="p", story_id="S1", metric_name="conv",
            baseline="18%", observed="22%",
            direction=OutcomeDirection.IMPROVED, window="7d",
        )
        await repo.add(o)
        rows = await repo.list_for_project("p")
        assert len(rows) == 1
        assert rows[0].direction == OutcomeDirection.IMPROVED

        for_story = await repo.list_for_story("p", "S1")
        assert len(for_story) == 1
