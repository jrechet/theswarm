"""F1b — run_api_cycle emits DemoReady with correct report_id and play_url."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from theswarm.api import run_api_cycle
from theswarm.application.events.bus import EventBus
from theswarm.domain.reporting.entities import DemoReport
from theswarm.domain.reporting.events import DemoReady


class _FakeReportRepo:
    def __init__(self) -> None:
        self.saved: list[DemoReport] = []

    async def save(self, report: DemoReport) -> None:
        self.saved.append(report)


async def _collect(bus: EventBus) -> list:
    events: list = []

    async def _handler(e) -> None:
        events.append(e)

    bus.subscribe_all(_handler)
    return events


async def test_run_api_cycle_publishes_demo_ready_with_play_url():
    bus = EventBus()
    events = await _collect(bus)
    repo = _FakeReportRepo()

    fake_result = {
        "cost_usd": 0.12,
        "prs": [{"number": 42}],
        "reviews": [{"decision": "APPROVE", "pr_number": 42}],
        "date": "2026-04-19",
    }

    with patch(
        "theswarm.cycle.run_daily_cycle",
        new=AsyncMock(return_value=fake_result),
    ):
        await run_api_cycle(
            cycle_id="cyc-1",
            repo="owner/todo-app",
            description="test",
            callback_url="",
            allowed_repos=[],
            event_bus=bus,
            report_repo=repo,
            base_path="/swarm",
        )

    demo_events = [e for e in events if isinstance(e, DemoReady)]
    assert len(demo_events) == 1, f"expected 1 DemoReady, got {events}"

    demo = demo_events[0]
    assert len(repo.saved) == 1
    saved = repo.saved[0]

    assert demo.report_id == saved.id
    assert demo.project_id == "owner/todo-app"
    assert demo.play_url == f"/swarm/demos/{saved.id}/play"
    assert demo.title.startswith("owner/todo-app — ")
    assert demo.thumbnail_url == ""
    assert str(demo.cycle_id) == "cyc-1"


async def test_run_api_cycle_skips_demo_ready_when_event_bus_missing():
    repo = _FakeReportRepo()
    fake_result = {"cost_usd": 0.0, "prs": [], "reviews": [], "date": "2026-04-19"}

    with patch(
        "theswarm.cycle.run_daily_cycle",
        new=AsyncMock(return_value=fake_result),
    ):
        await run_api_cycle(
            cycle_id="cyc-2",
            repo="owner/app",
            description="",
            callback_url="",
            allowed_repos=[],
            event_bus=None,
            report_repo=repo,
        )

    assert repo.saved == []


async def test_run_api_cycle_publishes_demo_ready_without_report_repo():
    bus = EventBus()
    events = await _collect(bus)
    fake_result = {"cost_usd": 0.0, "prs": [], "reviews": [], "date": "2026-04-19"}

    with patch(
        "theswarm.cycle.run_daily_cycle",
        new=AsyncMock(return_value=fake_result),
    ):
        await run_api_cycle(
            cycle_id="cyc-3",
            repo="owner/app",
            description="",
            callback_url="",
            allowed_repos=[],
            event_bus=bus,
            report_repo=None,
        )

    demo_events = [e for e in events if isinstance(e, DemoReady)]
    assert len(demo_events) == 1
    assert demo_events[0].play_url.startswith("/demos/")


async def test_run_api_cycle_threads_thumbnail_url_from_demo_report():
    """F4 — `thumbnail_path` from `result["demo_report"]` becomes `thumbnail_url`."""
    bus = EventBus()
    events = await _collect(bus)
    repo = _FakeReportRepo()
    fake_result = {
        "cost_usd": 0.0,
        "prs": [],
        "reviews": [],
        "date": "2026-04-19",
        "demo_report": {"thumbnail_path": "cyc/thumbnail/pr_42_thumb.jpg"},
    }

    with patch(
        "theswarm.cycle.run_daily_cycle",
        new=AsyncMock(return_value=fake_result),
    ):
        await run_api_cycle(
            cycle_id="cyc-5",
            repo="owner/app",
            description="",
            callback_url="",
            allowed_repos=[],
            event_bus=bus,
            report_repo=repo,
            base_path="/swarm",
        )

    demo = next(e for e in events if isinstance(e, DemoReady))
    assert demo.thumbnail_url == "/swarm/artifacts/cyc/thumbnail/pr_42_thumb.jpg"


async def test_run_api_cycle_base_path_prefixes_play_url():
    bus = EventBus()
    events = await _collect(bus)
    repo = _FakeReportRepo()
    fake_result = {"cost_usd": 0.0, "prs": [], "reviews": [], "date": "2026-04-19"}

    with patch(
        "theswarm.cycle.run_daily_cycle",
        new=AsyncMock(return_value=fake_result),
    ):
        await run_api_cycle(
            cycle_id="cyc-4",
            repo="owner/app",
            description="",
            callback_url="",
            allowed_repos=[],
            event_bus=bus,
            report_repo=repo,
            base_path="/swarm/",
        )

    demo = next(e for e in events if isinstance(e, DemoReady))
    assert demo.play_url.startswith("/swarm/demos/")
    assert "//" not in demo.play_url
