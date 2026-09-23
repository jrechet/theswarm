"""V2 runtime, M2: the trace a cycle leaves behind.

cycle → phase → node → claude.call, exported to Seq; the id on the cycle
row and on the tracker record; log events carrying @tr/@sp.
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from claude_agent_sdk import ResultMessage, SystemMessage
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from theswarm.config import CycleConfig
from theswarm.infrastructure import tracing
from theswarm.tools import claude as claude_mod
from theswarm.tools.claude import ClaudeCLI


@pytest.fixture
def exporter():
    memory = InMemorySpanExporter()
    tracing.setup_tracing(seq_url="", exporter=memory, batch=False)
    yield memory
    tracing.shutdown_tracing()


def _init() -> SystemMessage:
    return SystemMessage(subtype="init", data={"apiKeySource": "none", "session_id": "s-1"})


def _result(**overrides) -> ResultMessage:
    fields = dict(
        subtype="success", duration_ms=10, duration_api_ms=8, is_error=False,
        num_turns=2, session_id="s-1", total_cost_usd=0.25,
        usage={"input_tokens": 100, "output_tokens": 40}, result="ok",
    )
    fields.update(overrides)
    return ResultMessage(**fields)


def _fake_query(*messages):
    async def fake(prompt, options):
        for message in messages:
            yield message
    return fake


# ── claude.call ──────────────────────────────────────────────────────


async def test_a_claude_call_is_a_span_with_its_cost(exporter, monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "sdk")
    monkeypatch.setattr(claude_mod, "_sdk_query", _fake_query(_init(), _result()))

    await ClaudeCLI(model="haiku").run("go", workdir="/ws", permission_mode="acceptEdits")

    (call,) = [s for s in exporter.get_finished_spans() if s.name == "claude.call"]
    attrs = call.attributes
    assert attrs["swarm.backend"] == "sdk"
    assert attrs["swarm.model"] == "claude-haiku-4-5"
    assert attrs["swarm.profile"] == "edit"
    assert attrs["swarm.cost_usd"] == 0.25
    assert attrs["swarm.input_tokens"] == 100
    assert attrs["swarm.output_tokens"] == 40
    assert attrs["swarm.turns"] == 2
    assert attrs["swarm.session_id"] == "s-1"
    assert call.status.status_code.name == "UNSET"


async def test_a_failed_claude_call_marks_its_span(exporter, monkeypatch):
    monkeypatch.setenv("SWARM_CLAUDE_BACKEND", "sdk")
    monkeypatch.setattr(claude_mod, "_sdk_query", _fake_query(
        _init(), _result(subtype="error_during_execution", is_error=True, result="broke"),
    ))

    with pytest.raises(RuntimeError):
        await ClaudeCLI(model="haiku").run("go")

    (call,) = [s for s in exporter.get_finished_spans() if s.name == "claude.call"]
    assert call.status.status_code.name == "ERROR"
    assert "broke" in call.status.description


# ── phases and nodes ─────────────────────────────────────────────────


async def test_every_phase_of_a_cycle_is_a_span_with_its_role(exporter, tmp_path):
    from theswarm.cycle import run_daily_cycle

    def graph(state: dict) -> MagicMock:
        g = MagicMock()
        g.ainvoke = AsyncMock(return_value=state)
        return g

    mock_github = MagicMock()
    mock_github.ensure_branch_protection = AsyncMock()
    mock_github.get_open_prs = AsyncMock(return_value=[])
    base_state = {
        "team_id": "t", "github_repo": "owner/repo", "github": mock_github,
        "claude": SimpleNamespace(on_event=None), "workspace": str(tmp_path),
    }
    config = CycleConfig(github_repo="owner/repo", team_id="t", workspace_dir=str(tmp_path))

    with patch("theswarm.cycle.build_po_graph", return_value=graph({"tokens_used": 0, "cost_usd": 0.0, "daily_plan": "p"})), \
         patch("theswarm.cycle.build_techlead_graph", return_value=graph({"tokens_used": 0, "cost_usd": 0.0})), \
         patch("theswarm.cycle.build_dev_graph", return_value=graph({"tokens_used": 0, "cost_usd": 0.0, "task": None, "pr": None})), \
         patch("theswarm.cycle.build_qa_graph", return_value=graph({"tokens_used": 0, "cost_usd": 0.0, "demo_report": {"overall_status": "green", "date": "d"}})), \
         patch("theswarm.cycle._ensure_workspace", new_callable=AsyncMock), \
         patch("theswarm.cycle._pull_latest", new_callable=AsyncMock), \
         patch("theswarm.cycle._build_base_state", return_value=base_state), \
         patch("theswarm.cycle_log.append_cycle_log", new_callable=AsyncMock), \
         patch("theswarm.cycle._write_cycle_learnings", new_callable=AsyncMock), \
         patch("theswarm.tools.git.cleanup_workspace", new_callable=AsyncMock):
        await run_daily_cycle(config)

    phases = {s.name: s for s in exporter.get_finished_spans() if s.name.startswith("phase.")}
    for name, role in (
        ("phase.po_morning", "PO"), ("phase.techlead_breakdown", "TechLead"),
        ("phase.dev_iter", "Dev"), ("phase.qa", "QA"), ("phase.po_evening", "PO"),
    ):
        assert name in phases, sorted(phases)
        assert phases[name].attributes["swarm.role"] == role
        assert phases[name].attributes["swarm.budget_s"] > 0


async def test_every_node_of_an_agent_graph_is_a_span(exporter):
    from theswarm.agents.po import build_po_graph

    with tracing.span("phase.po_morning"):
        await build_po_graph().ainvoke({"phase": "morning"})

    spans = exporter.get_finished_spans()
    nodes = {s.name for s in spans if s.name.startswith("node.")}
    assert {"node.load_context", "node.select_daily_issues", "node.write_daily_plan"} <= nodes
    phase = next(s for s in spans if s.name == "phase.po_morning")
    node = next(s for s in spans if s.name == "node.load_context")
    assert node.parent.span_id == phase.context.span_id
    assert node.attributes["swarm.node"] == "load_context"


def test_traced_node_keeps_the_node_name_for_agents_md():
    from theswarm.agents.base import traced_node

    async def implement_task(state):
        return {"x": 1}

    wrapped = traced_node("implement", implement_task)
    assert wrapped.__name__ == "implement_task"


# ── logs meet traces ─────────────────────────────────────────────────


def test_log_events_carry_the_trace_id_inside_a_span(exporter):
    from theswarm.presentation.web.server import SeqCLEFHandler

    handler = SeqCLEFHandler("http://seq.test", None)
    handler._timer.cancel()
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "hello %s", ("w",), None)

    handler.emit(record)
    with tracing.span("cycle"):
        expected = tracing.current_trace_id()
        handler.emit(record)

    outside, inside = (json.loads(e) for e in handler._buffer)
    assert "@tr" not in outside
    assert inside["@tr"] == expected
    assert len(inside["@sp"]) == 16
    assert inside["@mt"] == "hello w"


# ── the id on the row and on the record ──────────────────────────────


async def test_the_trace_id_is_persisted_with_the_cycle(tmp_path):
    from datetime import datetime, timezone

    from theswarm.domain.cycles.entities import Cycle, CycleStatus
    from theswarm.domain.cycles.value_objects import CycleId
    from theswarm.infrastructure.persistence.sqlite_repos import (
        SQLiteCycleRepository, init_db,
    )

    db = await init_db(str(tmp_path / "t.db"))
    try:
        repo = SQLiteCycleRepository(db)
        cycle = Cycle(
            id=CycleId("abc123"), project_id="owner/repo", status=CycleStatus.RUNNING,
            started_at=datetime.now(timezone.utc), trace_id="f" * 32,
        )
        await repo.save(cycle)
        loaded = await repo.get(CycleId("abc123"))
        assert loaded is not None and loaded.trace_id == "f" * 32
        # the migration is idempotent: a second init on the same file is fine
        await init_db(str(tmp_path / "t.db"))
    finally:
        await db.close()


async def test_the_completion_handler_keeps_the_trace_id():
    from datetime import datetime, timezone

    from theswarm.application.events.persistence_handlers import CyclePersistenceHandler
    from theswarm.domain.cycles.entities import Cycle, CycleStatus
    from theswarm.domain.cycles.events import CycleCompleted, CycleStarted
    from theswarm.domain.cycles.value_objects import CycleId

    saved: list[Cycle] = []

    class Repo:
        async def save(self, cycle):
            saved.append(cycle)

        async def get(self, cycle_id):
            return saved[-1] if saved else None

    handler = CyclePersistenceHandler(Repo())
    await handler._on_started(CycleStarted(
        cycle_id=CycleId("c1"), project_id="p", triggered_by="web", trace_id="a" * 32,
    ))
    await handler._on_completed(CycleCompleted(
        cycle_id=CycleId("c1"), project_id="p", total_cost_usd=1.0, prs_opened=0, prs_merged=0,
    ))
    assert saved[0].trace_id == "a" * 32
    assert saved[-1].status == CycleStatus.COMPLETED
    assert saved[-1].trace_id == "a" * 32


def test_the_tracker_record_has_a_trace_id_and_the_theater_links_it(monkeypatch):
    from theswarm.api import CycleRecord, CycleStatus
    from theswarm.presentation.web.routes.v2 import trace_url

    record = CycleRecord(
        id="x", repo="o/r", description="", callback_url="",
        status=CycleStatus.RUNNING, created_at="now",
    )
    assert record.trace_id == ""
    assert trace_url("", "https://logs.example") == ""
    assert trace_url("ab" * 16, "") == ""
    url = trace_url("ab" * 16, "https://logs.example/")
    assert url.startswith("https://logs.example/#/events?filter=")
    assert "%40tr" in url and "ab" * 16 in url
