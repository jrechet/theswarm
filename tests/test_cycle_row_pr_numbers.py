"""A completed cycle's row holds the PR numbers the cycle really opened.

`CycleCompleted` used to carry counts only, and the persistence handler
rebuilt the numbers as `range(1, n + 1)`: prod cycle a6d93287668b opened
and merged #270, #271 and #272 on concert-tour-app, and
`GET /api/cycles/a6d93287668b` answered `prs_opened: [1, 2, 3]`.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from theswarm.api import run_api_cycle
from theswarm.application.events.bus import EventBus
from theswarm.application.events.persistence_handlers import CyclePersistenceHandler
from theswarm.domain.cycles.entities import Cycle
from theswarm.domain.cycles.events import CycleCompleted, CycleStarted
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository, init_db


@pytest.fixture(autouse=True)
def _own_dashboard_state(monkeypatch):
    # run_api_cycle leaves the cycle's cost in the process-wide dashboard
    # state, and test_dashboard_endpoints reads it as "idle" afterwards.
    from theswarm import dashboard

    monkeypatch.setattr(dashboard, "_state", dashboard.DashboardState())


def _pr(number: int) -> dict:
    return {"number": number, "url": f"https://github.com/o/r/pull/{number}"}


async def _run(tmp_path, cycle_id: str, result: dict) -> tuple[Cycle | None, list]:
    """Run one API cycle over a fake result; the row it left, and the events."""
    db = await init_db(str(tmp_path / "swarm.db"))
    try:
        repo = SQLiteCycleRepository(db)
        bus = EventBus()
        handler = CyclePersistenceHandler(repo)
        bus.subscribe(CycleStarted, handler.handle)
        bus.subscribe(CycleCompleted, handler.handle)
        events: list = []

        async def _record(event) -> None:
            events.append(event)

        bus.subscribe_all(_record)

        with patch("theswarm.cycle.run_daily_cycle", new=AsyncMock(return_value=result)):
            await run_api_cycle(
                cycle_id=cycle_id,
                repo="jrechet/concert-tour-app",
                description="",
                callback_url="",
                allowed_repos=[],
                event_bus=bus,
            )
        return await repo.get(CycleId(cycle_id)), events
    finally:
        await db.close()


async def test_the_row_holds_the_real_numbers_of_the_prs(tmp_path):
    result = {
        "date": "2026-09-23",
        "cost_usd": 4.2,
        "prs": [_pr(270), _pr(271), _pr(272)],
        "reviews": [{"decision": "APPROVE", "pr_number": n} for n in (270, 271, 272)],
        "merged_prs": [270, 271, 272],
        "held_prs": [],
    }

    row, _ = await _run(tmp_path, "a6d93287668b", result)

    assert row is not None and row.status == CycleStatus.COMPLETED
    assert row.prs_opened == (270, 271, 272)
    assert row.prs_merged == (270, 271, 272)


async def test_a_held_pr_is_opened_not_merged_and_a_repeat_counts_once(tmp_path):
    # SELF_REPO: #165 merged at the end of the cycle, #164 could not be and
    # stays held; #165 was pushed onto twice (a REQUEST_CHANGES round) and
    # appears twice in `prs`, and both approvals are in `reviews`.
    result = {
        "date": "2026-09-22",
        "cost_usd": 1.0,
        "prs": [_pr(164), _pr(165), _pr(165)],
        "reviews": [
            {"decision": "APPROVE", "pr_number": 164},
            {"decision": "APPROVE", "pr_number": 165},
            {"decision": "APPROVE", "pr_number": 165},
        ],
        "merged_prs": [165],
        "held_prs": [164],
    }

    row, events = await _run(tmp_path, "c-self", result)

    assert row is not None
    assert row.prs_opened == (164, 165)
    assert row.prs_merged == (165,)
    [completed] = [e for e in events if isinstance(e, CycleCompleted)]
    assert completed.opened_prs == (164, 165)
    assert completed.merged_prs == (165,)
    assert completed.held_prs == (164,)
    # The counts stay for whoever still reads them, and agree with the numbers.
    assert (completed.prs_opened, completed.prs_merged) == (2, 1)


async def test_an_event_with_counts_only_never_invents_numbers():
    saved: list[Cycle] = []

    class Repo:
        async def save(self, cycle: Cycle) -> None:
            saved.append(cycle)

        async def get(self, cycle_id: CycleId) -> Cycle | None:
            return saved[-1] if saved else None

    handler = CyclePersistenceHandler(Repo())
    await handler.handle(CycleStarted(cycle_id=CycleId("old"), project_id="o/r"))
    await handler.handle(CycleCompleted(
        cycle_id=CycleId("old"), project_id="o/r", prs_opened=3, prs_merged=3,
    ))

    assert saved[-1].status == CycleStatus.COMPLETED
    assert saved[-1].prs_opened == ()
    assert saved[-1].prs_merged == ()
