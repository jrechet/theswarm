"""Tests for the RoleAssignmentService (codename allocation + roster)."""

from __future__ import annotations

import pytest

from theswarm.application.services.role_assignment_service import RoleAssignmentService
from theswarm.domain.agents.entities import PORTFOLIO_PROJECT_ID
from theswarm.domain.agents.events import RoleAssigned
from theswarm.domain.agents.value_objects import CORE_PROJECT_ROLES, AgentRole
from theswarm.infrastructure.agents.role_assignment_repo import (
    SQLiteRoleAssignmentRepository,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db


@pytest.fixture()
async def repo(tmp_path):
    conn = await init_db(str(tmp_path / "svc.db"))
    try:
        yield SQLiteRoleAssignmentRepository(conn)
    finally:
        await conn.close()


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def publish(self, event: object) -> None:
        self.events.append(event)


POOL = ("Mei", "Aarav", "Kenji", "Ines", "Oluwa", "Priya", "Sana", "Tomas")


class TestRoleAssignmentService:
    async def test_assign_creates_unique_codename(self, repo):
        bus = _FakeBus()
        svc = RoleAssignmentService(repo, event_bus=bus, pool=POOL)

        po = await svc.assign("demo", AgentRole.PO)
        dev = await svc.assign("demo", AgentRole.DEV)

        assert po.codename in POOL
        assert dev.codename in POOL
        assert po.codename != dev.codename
        assert len(bus.events) == 2
        assert all(isinstance(e, RoleAssigned) for e in bus.events)

    async def test_assign_is_idempotent(self, repo):
        svc = RoleAssignmentService(repo, pool=POOL)
        a1 = await svc.assign("demo", AgentRole.PO)
        a2 = await svc.assign("demo", AgentRole.PO)
        assert a1.id == a2.id
        assert a1.codename == a2.codename

    async def test_assign_core_roster_creates_four_distinct_codenames(self, repo):
        svc = RoleAssignmentService(repo, pool=POOL)
        roster = await svc.assign_core_roster("demo")

        assert [a.role for a in roster] == list(CORE_PROJECT_ROLES)
        codenames = {a.codename for a in roster}
        assert len(codenames) == 4

    async def test_portfolio_role_uses_portfolio_project_id(self, repo):
        svc = RoleAssignmentService(repo, pool=POOL)
        scout = await svc.assign("demo", AgentRole.SCOUT)
        assert scout.project_id == PORTFOLIO_PROJECT_ID

        # Re-assigning from any project returns the same portfolio instance.
        scout_again = await svc.assign("other-project", AgentRole.SCOUT)
        assert scout_again.id == scout.id

    async def test_codename_map_includes_portfolio_roles(self, repo):
        svc = RoleAssignmentService(repo, pool=POOL)
        await svc.assign_core_roster("demo")
        await svc.assign("demo", AgentRole.SCOUT)

        mapping = await svc.codename_map("demo")
        assert set(mapping.keys()) >= {"po", "techlead", "dev", "qa", "scout"}
        # All values are strings from the pool and distinct.
        assert all(v in POOL for v in mapping.values())
        assert len(set(mapping.values())) == len(mapping)

    async def test_explicit_codename_override(self, repo):
        svc = RoleAssignmentService(repo, pool=POOL)
        a = await svc.assign("demo", AgentRole.DEV, codename="Yasmin")
        assert a.codename == "Yasmin"

    async def test_event_not_raised_on_bus_failure(self, repo):
        class BoomBus:
            async def publish(self, event):
                raise RuntimeError("bus down")

        svc = RoleAssignmentService(repo, event_bus=BoomBus(), pool=POOL)
        # Must succeed despite the event bus exploding.
        a = await svc.assign("demo", AgentRole.PO)
        assert a.codename in POOL
