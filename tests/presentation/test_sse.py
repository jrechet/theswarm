"""Tests for presentation/web/sse.py."""

from __future__ import annotations

import asyncio
import json

import pytest

from theswarm.domain.cycles.events import AgentActivity, CycleStarted
from theswarm.domain.cycles.value_objects import CycleId
from theswarm.presentation.web.sse import SSEHub


class TestSSEHub:
    def test_initial_state(self):
        hub = SSEHub()
        assert hub.client_count == 0
        assert hub.history == []

    def test_connect_disconnect(self):
        hub = SSEHub()
        q = hub.connect()
        assert hub.client_count == 1

        hub.disconnect(q)
        assert hub.client_count == 0

    def test_disconnect_unknown(self):
        hub = SSEHub()
        q: asyncio.Queue[str] = asyncio.Queue()
        hub.disconnect(q)  # should not raise

    async def test_broadcast(self):
        hub = SSEHub()
        q = hub.connect()

        event = CycleStarted(project_id="p1", triggered_by="test")
        await hub.broadcast(event)

        assert not q.empty()
        data = json.loads(q.get_nowait())
        assert data["type"] == "CycleStarted"
        assert data["project_id"] == "p1"

    async def test_broadcast_multiple_clients(self):
        hub = SSEHub()
        q1 = hub.connect()
        q2 = hub.connect()

        await hub.broadcast(CycleStarted(project_id="p1"))

        assert not q1.empty()
        assert not q2.empty()

    async def test_broadcast_no_clients(self):
        hub = SSEHub()
        await hub.broadcast(CycleStarted(project_id="p1"))  # no error

    async def test_full_queue_disconnects_client(self):
        hub = SSEHub(max_history=10)
        q = hub.connect()

        # Fill the queue
        for i in range(55):
            await hub.broadcast(CycleStarted(project_id=f"p{i}"))

        # Client with full queue gets disconnected
        assert hub.client_count == 0

    async def test_history_maintained(self):
        hub = SSEHub(max_history=5)
        for i in range(10):
            await hub.broadcast(CycleStarted(project_id=f"p{i}"))

        assert len(hub.history) == 5

    async def test_event_stream(self):
        hub = SSEHub()
        q = hub.connect()

        await hub.broadcast(CycleStarted(project_id="p1"))

        stream = hub.event_stream(q)
        msg = await stream.__anext__()
        assert msg.startswith("data: ")
        assert msg.endswith("\n\n")
        payload = json.loads(msg[6:].strip())
        assert payload["type"] == "CycleStarted"

    async def test_broadcast_agent_activity(self):
        hub = SSEHub()
        q = hub.connect()

        event = AgentActivity(
            cycle_id=CycleId("c1"),
            project_id="p1",
            agent="dev",
            action="implement",
            detail="Working on feature",
            metadata={"file": "app.py"},
        )
        await hub.broadcast(event)

        data = json.loads(q.get_nowait())
        assert data["type"] == "AgentActivity"
        assert data["agent"] == "dev"
        assert data["action"] == "implement"
        assert data["metadata"]["file"] == "app.py"
