"""Phase K infrastructure tests — Architect repos."""

from __future__ import annotations

import pytest

from theswarm.domain.architect.entities import (
    DirectionBrief,
    PavedRoadRule,
    PortfolioADR,
)
from theswarm.domain.architect.value_objects import (
    ADRStatus,
    BriefScope,
    RuleSeverity,
)
from theswarm.infrastructure.architect.adr_repo import (
    SQLitePortfolioADRRepository,
)
from theswarm.infrastructure.architect.brief_repo import (
    SQLiteDirectionBriefRepository,
)
from theswarm.infrastructure.architect.rule_repo import (
    SQLitePavedRoadRuleRepository,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "architect.db"))
    yield conn
    await conn.close()


class TestPavedRoadRuleRepo:
    async def test_upsert_preserves_id_on_same_name(self, db):
        repo = SQLitePavedRoadRuleRepository(db)
        r1 = PavedRoadRule(
            id="r1", name="python-uv", rule="use uv", tags=("python",),
        )
        got1 = await repo.upsert(r1)
        assert got1.id == "r1"

        r2 = PavedRoadRule(
            id="r2", name="python-uv", rule="use uv (updated)",
            severity=RuleSeverity.REQUIRED, tags=("python", "deps"),
        )
        got2 = await repo.upsert(r2)
        assert got2.id == "r1"
        assert got2.severity == RuleSeverity.REQUIRED
        assert "deps" in got2.tags

        rows = await repo.list_all()
        assert len(rows) == 1


class TestPortfolioADRRepo:
    async def test_add_update_list(self, db):
        repo = SQLitePortfolioADRRepository(db)
        a = PortfolioADR(
            id="a1", title="Adopt LangGraph",
            context="c", decision="d", project_id="",
        )
        await repo.add(a)

        got = await repo.get_by_id("a1")
        assert got is not None

        from dataclasses import replace
        accepted = replace(got, status=ADRStatus.ACCEPTED)
        await repo.update(accepted)

        refreshed = await repo.get_by_id("a1")
        assert refreshed.status == ADRStatus.ACCEPTED

        # portfolio-wide visible in project-scoped listing
        rows = await repo.list_all(project_id="proj-42")
        assert any(r.id == "a1" for r in rows)

    async def test_list_all_project_scoped(self, db):
        repo = SQLitePortfolioADRRepository(db)
        await repo.add(PortfolioADR(id="a1", title="port", project_id=""))
        await repo.add(PortfolioADR(id="a2", title="proj", project_id="p1"))
        await repo.add(PortfolioADR(id="a3", title="other", project_id="p2"))
        rows = await repo.list_all(project_id="p1")
        ids = {r.id for r in rows}
        assert "a1" in ids and "a2" in ids and "a3" not in ids


class TestDirectionBriefRepo:
    async def test_add_and_list_portfolio_and_project(self, db):
        repo = SQLiteDirectionBriefRepository(db)
        b1 = DirectionBrief(
            id="b1", title="portfolio Q2",
            scope=BriefScope.PORTFOLIO, project_id="",
            focus_areas=("resilience", "observability"),
            risks=("rate limits",),
        )
        b2 = DirectionBrief(
            id="b2", title="project Q2",
            scope=BriefScope.PROJECT, project_id="p1",
        )
        await repo.add(b1)
        await repo.add(b2)

        portfolio = await repo.list_portfolio()
        assert len(portfolio) == 1
        assert portfolio[0].focus_areas == ("resilience", "observability")
        assert portfolio[0].risks == ("rate limits",)

        project = await repo.list_for_project("p1")
        assert len(project) == 1
        assert project[0].id == "b2"
