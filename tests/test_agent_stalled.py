"""The watchdog's word reaches the theater (A1).

It was built without a callback (`cycle.py`): "Agent 'Dev' idle for 760s" went
to the logs and nowhere else, and the owner could not tell a stuck agent from
a busy one ("je n'arrive pas à savoir … si c'est bloqué", 2026-11-11). Now a
silence is an `AgentStalled` on the bus, kept with the cycle's events, said in
the theater's feed, and the active station says how long it has been quiet.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from theswarm.application.services.watchdog import AgentWatchdog, WatchdogEvent
from theswarm.cycle import STALL_ROLES, stall_reporter


def _event(role="Dev", warning=1, last="Bash: pytest -q"):
    return WatchdogEvent(role=role, idle_seconds=760.0, warning_count=warning,
                         message=f"Agent '{role}' idle for 760s", last_message=last)


async def test_one_event_per_silence_and_only_for_an_agent_of_a_phase():
    told: list = []

    async def on_stalled(event):
        told.append(event)

    report = stall_reporter(on_stalled)
    await report(_event())
    await report(_event(warning=2))  # the same silence, later
    await report(_event(role="System"))  # speaks once, never retired
    await report(_event(role="Memory"))
    assert [e.role for e in told] == ["Dev"] and "Dev" in STALL_ROLES

    async def deaf(event):
        raise RuntimeError("bus down")

    await stall_reporter(deaf)(_event())  # never stops a cycle
    await stall_reporter(None)(_event())


def test_speaking_again_ends_the_silence():
    dog = AgentWatchdog()
    dog.heartbeat("Dev", "Read src/app.py")
    dog._agents["Dev"].timed_out = True
    dog.heartbeat("Dev", "Edit src/app.py")
    assert dog._agents["Dev"].timed_out is False  # a later silence is reported again


async def test_the_api_publishes_it_and_the_store_keeps_it():
    from theswarm.api import _stall_publisher
    from theswarm.application.events.cycle_event_persistence import CycleEventPersistenceHandler
    from theswarm.domain.cycles.events import AgentStalled

    published: list = []
    bus = SimpleNamespace(publish=None)

    async def publish(event):
        published.append(event)

    bus.publish = publish
    assert _stall_publisher(None, "c1", "o/r") is None  # the CLI: logs only
    await _stall_publisher(bus, "c1", "o/r")(_event())
    event = published[0]
    assert isinstance(event, AgentStalled) and str(event.cycle_id) == "c1"
    assert event.agent == "Dev" and event.idle_seconds == 760.0 and event.last_said == "Bash: pytest -q"

    kept: list = []

    class Store:
        async def append(self, **row):
            kept.append(row)

    await CycleEventPersistenceHandler(Store()).handle(event)
    assert kept[0]["event_type"] == "AgentStalled" and kept[0]["payload"]["agent"] == "Dev"


async def test_the_feed_says_it():
    from theswarm.application.queries.get_agent_thoughts import GetAgentThoughtsQuery, stalled_words

    row = SimpleNamespace(event_type="AgentStalled", occurred_at=datetime(2026, 11, 14, 18, 0, tzinfo=timezone.utc),
                          payload={"agent": "Dev", "idle_seconds": 760.0, "last_said": "Bash: pytest -q"})

    class Store:
        async def list_for_cycle(self, cycle_id):
            return [row]

    entries = await GetAgentThoughtsQuery(Store()).execute("c1", include_activity=True)
    assert entries[0].kind == "stalled" and entries[0].agent == "Dev"
    assert entries[0].text == "Silent for 13 min — last said: Bash: pytest -q"
    assert await GetAgentThoughtsQuery(Store()).execute("c1") == []  # thoughts only: not a thought
    assert stalled_words(30) == "Silent for 1 min"


async def test_the_theater_says_the_silence_on_the_station_and_in_the_feed(tmp_path):
    """A running cycle whose Dev said nothing for 13 min: the station says so in
    the colour of a problem, and the stored `AgentStalled` is a line of the feed."""
    import time
    from unittest.mock import AsyncMock, patch

    from httpx import ASGITransport, AsyncClient

    from theswarm.api import CycleRequest, CycleStatus, get_cycle_tracker
    from theswarm.application.events.bus import EventBus
    from theswarm.application.services import progress_bridge
    from theswarm.domain.cycles.events import AgentStalled
    from theswarm.domain.cycles.value_objects import CycleId
    from theswarm.infrastructure.persistence.cycle_event_store import SQLiteCycleEventStore
    from theswarm.infrastructure.persistence.sqlite_repos import (
        SQLiteCycleRepository,
        SQLiteProjectRepository,
        init_db,
    )
    from theswarm.presentation.web.app import create_web_app
    from theswarm.presentation.web.sse import SSEHub

    tracker = get_cycle_tracker()
    record = tracker.create(CycleRequest(repo="jrechet/concert-tour-app", issue_number=397))
    tracker.update_status(record.id, CycleStatus.RUNNING)
    progress_bridge.record_phase(record.id, "dev_iter")
    progress_bridge._PHASE_HISTORY[record.id][-1]["ts"] = time.time() - 2000
    progress_bridge.record_live_progress(record.id, "Dev", "Bash: python -m pytest -q")
    progress_bridge._LIVE_PROGRESS[(record.id, "Dev")]["ts"] = time.time() - 800
    conn = await init_db(str(tmp_path / "t.db"))
    try:
        bus = EventBus()
        app = create_web_app(SQLiteProjectRepository(conn), SQLiteCycleRepository(conn),
                             bus, SSEHub(), base_path="/swarm", db=conn,
                             cycle_event_store=SQLiteCycleEventStore(conn))
        await bus.publish(AgentStalled(cycle_id=CycleId(record.id), project_id="jrechet/concert-tour-app",
                                       agent="Dev", idle_seconds=760.0, last_said="Bash: python -m pytest -q"))
        with patch("theswarm.tools.github.GitHubClient") as klass:
            klass.return_value.get_issue = AsyncMock(return_value={"number": 397, "title": "Next concert"})
            klass.return_value.get_issues = AsyncMock(return_value=[])
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
                html = (await client.get(f"/cycles/{record.id}/stage")).text
    finally:
        tracker._cycles.pop(record.id, None)
        progress_bridge._PHASE_HISTORY.pop(record.id, None)
        progress_bridge._LIVE_PROGRESS.pop((record.id, "Dev"), None)
        await conn.close()

    assert 'data-testid="station-quiet" data-stalled="true"' in html and "No word for 13 min" in html
    assert 'data-testid="feed-stalled"' in html and "Silent for 13 min" in html
