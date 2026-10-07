"""Requests — the one thing a customer writes (V3 M5): submit, plan, decline,
and the request following its feature's cycle and demo."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from theswarm.application.services.customers import CustomerService
from theswarm.application.services.requests import REQUEST_MARKER, RequestError, RequestService, RequestTracker
from theswarm.domain.customers.requests import Request
from theswarm.infrastructure.persistence.customer_repo import (
    SQLiteCustomerRepository,
    SQLiteMemberRepository,
    SQLiteRequestRepository,
)
from theswarm.infrastructure.persistence.sqlite_repos import SQLiteProjectRepository, init_db

NOW = datetime(2026, 10, 7, 14, 0, tzinfo=timezone.utc)
REPO = "jrechet/espace-client"


@pytest.fixture()
async def world(tmp_path):
    conn = await init_db(str(tmp_path / "t.db"))
    projects = SQLiteProjectRepository(conn)
    customers = CustomerService(SQLiteCustomerRepository(conn), SQLiteMemberRepository(conn), projects)
    tl = await customers.create("TLphone")
    project = await customers.assign_project(REPO, tl)
    requests = RequestService(SQLiteRequestRepository(conn), projects)
    yield SimpleNamespace(conn=conn, customers=customers, tl=tl, project=project, requests=requests, projects=projects)
    await conn.close()


class TestSubmit:
    async def test_a_member_s_need_is_received(self, world):
        r = await world.requests.submit(world.tl, "  Pouvoir exporter  les factures du mois en PDF ", "Chaque début de mois…",
                                        member_id="m1", author_name="Nadia", project=world.project, now=NOW)
        assert r.status == "received" and r.step == 0 and r.is_open
        assert r.title == "Pouvoir exporter les factures du mois en PDF" and r.project_id == world.project.id
        assert [s["state"] for s in r.steps()] == ["now", "next", "next", "next"]
        assert [x.id for x in await world.requests.inbox()] == [r.id]
        assert [x.id for x in await world.requests.for_customer(world.tl)] == [r.id]

    async def test_an_empty_line_is_refused(self, world):
        with pytest.raises(RequestError):
            await world.requests.submit(world.tl, "   ")

    async def test_a_long_title_is_cut(self, world):
        r = await world.requests.submit(world.tl, "x" * 200)
        assert len(r.title) == 120


class TestPlanAndDecline:
    async def test_planning_makes_the_issue_and_links_it(self, world):
        r = await world.requests.submit(world.tl, "Export des factures en PDF", "Un seul PDF par mois.",
                                        author_name="Nadia", now=NOW)
        github = SimpleNamespace(create_issue=AsyncMock(return_value={"number": 90}))
        planned = await world.requests.plan(r, world.tl, world.project, github=github, now=NOW + timedelta(hours=1))
        assert planned.status == "planned" and planned.feature_repo == REPO and planned.feature_issue_number == 90
        assert planned.project_id == world.project.id
        kwargs = github.create_issue.await_args.kwargs
        assert kwargs["title"] == "Export des factures en PDF" and kwargs["labels"] == ["status:backlog"]
        assert "Un seul PDF par mois." in kwargs["body"] and "Requested by Nadia (TLphone), 07 Oct 2026." in kwargs["body"]
        assert REQUEST_MARKER.format(id=r.id) in kwargs["body"]
        assert await world.requests.inbox() == []
        assert [s["state"] for s in planned.steps()] == ["done", "now", "next", "next"]

    async def test_the_owner_may_reword_the_feature(self, world):
        r = await world.requests.submit(world.tl, "export pdf", now=NOW)
        github = SimpleNamespace(create_issue=AsyncMock(return_value={"number": 91}))
        await world.requests.plan(r, world.tl, world.project, title="Monthly invoices as one PDF", body="Spec.", github=github)
        assert github.create_issue.await_args.kwargs["title"] == "Monthly invoices as one PDF"
        assert github.create_issue.await_args.kwargs["body"] == "Spec."

    async def test_only_a_received_request_is_planned(self, world):
        r = await world.requests.submit(world.tl, "export pdf", now=NOW)
        declined = await world.requests.decline(r, "Hors périmètre pour l'instant")
        assert declined.status == "declined" and declined.step == -1 and not declined.is_open
        assert [s["state"] for s in declined.steps()] == ["done", "off", "off", "off"]
        with pytest.raises(RequestError):
            await world.requests.plan(declined, world.tl, world.project, github=SimpleNamespace(create_issue=AsyncMock()))

    async def test_github_without_a_number_is_an_error(self, world):
        r = await world.requests.submit(world.tl, "export pdf", now=NOW)
        with pytest.raises(RequestError):
            await world.requests.plan(r, world.tl, world.project, github=SimpleNamespace(create_issue=AsyncMock(return_value={})))
        assert (await world.requests.get(r.id)).status == "received"


class TestTheRequestFollowsItsFeature:
    async def _planned(self, world) -> Request:
        r = await world.requests.submit(world.tl, "export pdf", now=NOW)
        return await world.requests.plan(r, world.tl, world.project, github=SimpleNamespace(create_issue=AsyncMock(return_value={"number": 90})))

    async def test_a_cycle_on_the_issue_means_building_and_its_demo_means_delivered(self, world):
        r = await self._planned(world)
        assert await world.requests.on_cycle_started(REPO, 90) == 1
        assert (await world.requests.get(r.id)).status == "building"
        assert await world.requests.on_cycle_started(REPO, 90) == 0  # already there
        assert await world.requests.on_demo_ready(REPO, 90, "rep-1") == 1
        delivered = await world.requests.get(r.id)
        assert delivered.status == "delivered" and delivered.demo_report_id == "rep-1"
        assert [s["state"] for s in delivered.steps()] == ["done", "done", "done", "done"]

    async def test_another_issue_or_repository_moves_nothing(self, world):
        await self._planned(world)
        assert await world.requests.on_cycle_started(REPO, 91) == 0
        assert await world.requests.on_cycle_started("jrechet/other", 90) == 0
        assert await world.requests.on_cycle_started(REPO, None) == 0

    async def test_the_tracker_reads_the_events_and_resolves_a_registered_id(self, world):
        r = await self._planned(world)
        tracker = RequestTracker(world.requests, world.projects)
        await tracker.on_cycle_started(SimpleNamespace(project_id=world.project.id, issue_number=90))
        assert (await world.requests.get(r.id)).status == "building"
        await tracker.on_demo_ready(SimpleNamespace(project_id=REPO, issue_number=90, report_id="rep-9"))
        assert (await world.requests.get(r.id)).status == "delivered"

    async def test_a_failing_tracker_never_raises(self, world):
        tracker = RequestTracker(SimpleNamespace(on_cycle_started=AsyncMock(side_effect=RuntimeError("db"))), None)
        await tracker.on_cycle_started(SimpleNamespace(project_id=REPO, issue_number=1))  # logged, not raised
