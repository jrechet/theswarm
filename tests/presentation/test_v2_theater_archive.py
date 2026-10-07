"""A finished cycle keeps its theater after a restart.

The tracker is in-memory: after any restart — every deploy — `/c/{id}` of
a finished cycle redirected to the V1 archive, and the theater's demo card
(#79: "show the demo to the user") was gone for every link already
shared. A finished cycle is now drawn from the database: its stations
done, its feed from the event store, its demo from the report store, its
issue from the number the cycle row now keeps (v032).
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.application.events.persistence_handlers import CyclePersistenceHandler
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.events import CycleStarted
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.domain.reporting.entities import DemoReport, ReportSummary
from theswarm.infrastructure.persistence.cycle_event_store import SQLiteCycleEventStore
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub

CID = "7f4f2188cd90"
T = datetime(2026, 9, 28, 18, 15, tzinfo=timezone.utc)


@pytest.fixture()
async def conn(tmp_path):
    db = await init_db(str(tmp_path / "archive.db"))
    yield db
    await db.close()


async def test_the_cycle_row_keeps_its_issue_number(conn):
    repo = SQLiteCycleRepository(conn)
    await repo.save(Cycle(id=CycleId(CID), project_id="jrechet/concert-tour-app",
                          status=CycleStatus.RUNNING, started_at=T, issue_number=404))

    assert (await repo.get(CycleId(CID))).issue_number == 404


async def test_a_started_cycle_is_written_with_its_issue(conn):
    repo = SQLiteCycleRepository(conn)
    handler = CyclePersistenceHandler(repo)

    await handler.handle(CycleStarted(cycle_id=CycleId(CID), project_id="jrechet/concert-tour-app",
                                      triggered_by="web", issue_number=404))

    assert (await repo.get(CycleId(CID))).issue_number == 404


async def test_an_older_database_gains_the_column(tmp_path):
    import aiosqlite

    path = str(tmp_path / "old.db")
    db = await init_db(path)
    await db.close()
    async with aiosqlite.connect(path) as raw:
        columns = {row[1] for row in await (await raw.execute("PRAGMA table_info(cycles)")).fetchall()}

    assert "issue_number" in columns


async def _page(conn, status: CycleStatus, path: str = f"/cycles/{CID}"):
    await SQLiteCycleRepository(conn).save(Cycle(
        id=CycleId(CID), project_id="jrechet/concert-tour-app", status=status,
        started_at=T, completed_at=T.replace(minute=24), issue_number=404,
    ))
    store = SQLiteCycleEventStore(conn)
    await store.append(CID, "AgentActivity", T, {"agent": "TechLead", "action": "review",
                                                 "detail": "PR #410: APPROVE"})
    reports = SQLiteReportRepository(conn)
    await reports.save(DemoReport(
        id="rpt-7f4f", cycle_id=CycleId(CID), project_id="jrechet/concert-tour-app",
        created_at=T.replace(minute=25),
        summary=ReportSummary(stories_completed=3, stories_total=3, prs_merged=3),
    ))
    app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn), EventBus(),
                         SSEHub(), base_path="/swarm", db=conn, report_repo=reports,
                         cycle_event_store=store)
    with patch("theswarm.tools.github.GitHubClient") as klass:
        klass.return_value.get_issue = AsyncMock(
            return_value={"number": 404, "title": "Count the concerts per country"})
        klass.return_value.get_issues = AsyncMock(return_value=[])
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            return await client.get(path)


async def test_a_finished_cycle_the_tracker_forgot_keeps_its_theater(conn):
    r = await _page(conn, CycleStatus.COMPLETED)

    assert r.status_code == 200
    assert "Count the concerts per country" in r.text
    assert 'data-testid="stage-demo"' in r.text and "/swarm/demos/rpt-7f4f" in r.text
    assert "PR #410: APPROVE" in r.text
    assert r.text.count('data-state="done"') == 4


async def test_its_stage_answers_too(conn):
    r = await _page(conn, CycleStatus.COMPLETED, path=f"/cycles/{CID}/stage")

    assert r.status_code == 200 and 'data-status="completed"' in r.text


async def test_a_cycle_the_database_still_calls_running_goes_to_the_archive(conn):
    """Nothing runs it any more (the tracker would know): the archive view
    says what the database knows, as before."""
    r = await _page(conn, CycleStatus.RUNNING)

    assert r.status_code == 200 and 'data-testid="orphan"' in r.text  # drawn from the row, said so (M4)
