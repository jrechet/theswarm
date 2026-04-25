"""ProgressBridge — live-progress cache behaviour."""

from __future__ import annotations

import pytest

from theswarm.application.events.bus import EventBus
from theswarm.application.services.progress_bridge import (
    ProgressBridge,
    _LIVE_PROGRESS,
    get_live_progress,
    record_live_progress,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    _LIVE_PROGRESS.clear()
    yield
    _LIVE_PROGRESS.clear()


def test_record_and_get_returns_latest_per_role():
    record_live_progress("c1", "PO", "Starting daily planning…")
    record_live_progress("c1", "PO", "Picked 3 backlog issues")
    record_live_progress("c1", "Dev", "Iteration 1/5")

    rows = get_live_progress("c1")
    by_role = {r["role"]: r["message"] for r in rows}
    assert by_role["PO"] == "Picked 3 backlog issues"
    assert by_role["Dev"] == "Iteration 1/5"


def test_get_filters_by_cycle_id():
    record_live_progress("c1", "PO", "msg1")
    record_live_progress("c2", "PO", "msg2")
    rows = get_live_progress("c1")
    assert len(rows) == 1
    assert rows[0]["message"] == "msg1"


def test_get_returns_empty_for_unknown_cycle():
    assert get_live_progress("none") == []


async def test_bridge_stashes_progress():
    bus = EventBus()
    bridge = ProgressBridge(event_bus=bus, cycle_id="c1", project_id="p1")
    await bridge("Dev", "Starting development loop…")
    rows = get_live_progress("c1")
    assert any(r["role"] == "Dev" and "development loop" in r["message"] for r in rows)
