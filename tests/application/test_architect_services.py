"""Phase K application tests — Architect services."""

from __future__ import annotations

import pytest

from theswarm.application.services.architect import (
    DirectionBriefService,
    PavedRoadService,
    PortfolioADRService,
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
    conn = await init_db(str(tmp_path / "architect_svc.db"))
    yield conn
    await conn.close()


class TestPavedRoadService:
    async def test_upsert_preserves_id(self, db):
        svc = PavedRoadService(SQLitePavedRoadRuleRepository(db))
        a = await svc.upsert(name="python-uv", rule="use uv")
        b = await svc.upsert(
            name="python-uv", rule="use uv (strict)",
            severity=RuleSeverity.REQUIRED,
        )
        assert a.id == b.id
        assert b.severity == RuleSeverity.REQUIRED
        assert b.is_blocking

    async def test_list_returns_all(self, db):
        svc = PavedRoadService(SQLitePavedRoadRuleRepository(db))
        await svc.upsert(name="a", rule="r1")
        await svc.upsert(name="b", rule="r2")
        rows = await svc.list()
        assert len(rows) == 2


class TestPortfolioADRService:
    async def test_propose_accept_reject(self, db):
        svc = PortfolioADRService(SQLitePortfolioADRRepository(db))
        adr = await svc.propose(title="Use LangGraph")
        assert adr.status == ADRStatus.PROPOSED

        accepted = await svc.accept(adr.id)
        assert accepted.status == ADRStatus.ACCEPTED
        assert accepted.is_active

        other = await svc.propose(title="other")
        rejected = await svc.reject(other.id)
        assert rejected.status == ADRStatus.REJECTED

    async def test_supersede(self, db):
        svc = PortfolioADRService(SQLitePortfolioADRRepository(db))
        old = await svc.propose(title="old")
        new = await svc.propose(title="new")
        result = await svc.supersede(old.id, new.id)
        assert result.status == ADRStatus.SUPERSEDED
        assert result.supersedes == new.id

    async def test_accept_missing_raises(self, db):
        svc = PortfolioADRService(SQLitePortfolioADRRepository(db))
        with pytest.raises(ValueError):
            await svc.accept("missing")

    async def test_list_scopes(self, db):
        svc = PortfolioADRService(SQLitePortfolioADRRepository(db))
        await svc.propose(title="portfolio", project_id="")
        await svc.propose(title="proj-a", project_id="p1")
        all_portfolio = await svc.list(project_id=None)
        assert len(all_portfolio) == 2
        project_view = await svc.list(project_id="p1")
        assert {a.title for a in project_view} == {"portfolio", "proj-a"}


class TestDirectionBriefService:
    async def test_record_portfolio_clears_project_id(self, db):
        svc = DirectionBriefService(SQLiteDirectionBriefRepository(db))
        b = await svc.record(
            title="Q2",
            scope=BriefScope.PORTFOLIO, project_id="ignored",
            focus_areas=("a", "b"), risks=("r",),
        )
        assert b.project_id == ""

        rows = await svc.list_portfolio()
        assert len(rows) == 1
        assert rows[0].focus_areas == ("a", "b")

    async def test_record_project_keeps_project_id(self, db):
        svc = DirectionBriefService(SQLiteDirectionBriefRepository(db))
        b = await svc.record(
            title="Q2", scope=BriefScope.PROJECT, project_id="p1",
        )
        assert b.project_id == "p1"

        rows = await svc.list_for_project("p1")
        assert len(rows) == 1
