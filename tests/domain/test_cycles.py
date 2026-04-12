"""Tests for domain/cycles — 100% coverage target."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from theswarm.domain.cycles.entities import Cycle, PhaseExecution
from theswarm.domain.cycles.events import (
    AgentActivity,
    BudgetExceeded,
    CycleCompleted,
    CycleFailed,
    CycleStarted,
    PhaseChanged,
)
from theswarm.domain.cycles.value_objects import (
    Budget,
    CycleId,
    CycleStatus,
    PhaseStatus,
    TokenUsage,
)


# ── CycleId ──────────────────────────────────────────────────────


class TestCycleId:
    def test_generate(self):
        cid = CycleId.generate()
        assert len(cid.value) == 12

    def test_str(self):
        cid = CycleId("abc123")
        assert str(cid) == "abc123"

    def test_uniqueness(self):
        ids = {CycleId.generate().value for _ in range(100)}
        assert len(ids) == 100


# ── TokenUsage ───────────────────────────────────────────────────


class TestTokenUsage:
    def test_total(self):
        t = TokenUsage(input_tokens=100, output_tokens=50)
        assert t.total == 150

    def test_add(self):
        a = TokenUsage(100, 50)
        b = TokenUsage(200, 100)
        c = a + b
        assert c.input_tokens == 300
        assert c.output_tokens == 150
        assert c.total == 450

    def test_defaults(self):
        t = TokenUsage()
        assert t.total == 0


# ── Budget ───────────────────────────────────────────────────────


class TestBudget:
    def test_remaining(self):
        b = Budget(role="dev", limit=1000, used=600)
        assert b.remaining == 400

    def test_remaining_exceeded(self):
        b = Budget(role="dev", limit=1000, used=1200)
        assert b.remaining == 0

    def test_percent_used(self):
        b = Budget(role="dev", limit=1000, used=750)
        assert b.percent_used == 75.0

    def test_percent_used_zero_limit(self):
        b = Budget(role="dev", limit=0, used=0)
        assert b.percent_used == 0.0

    def test_percent_used_capped(self):
        b = Budget(role="dev", limit=100, used=200)
        assert b.percent_used == 100.0

    def test_exceeded(self):
        assert Budget(role="dev", limit=100, used=101).exceeded is True
        assert Budget(role="dev", limit=100, used=100).exceeded is False
        assert Budget(role="dev", limit=100, used=50).exceeded is False

    def test_with_usage(self):
        b = Budget(role="dev", limit=1000, used=100)
        b2 = b.with_usage(200)
        assert b2.used == 300
        assert b.used == 100  # immutable


# ── PhaseExecution ───────────────────────────────────────────────


class TestPhaseExecution:
    def test_complete(self):
        now = datetime.now(timezone.utc)
        p = PhaseExecution(phase="morning", agent="po", started_at=now)
        assert p.status == PhaseStatus.RUNNING

        p2 = p.complete("Selected 3 stories", tokens=5000, cost=0.10)
        assert p2.status == PhaseStatus.COMPLETED
        assert p2.summary == "Selected 3 stories"
        assert p2.tokens_used == 5000
        assert p2.cost_usd == 0.10
        assert p2.completed_at is not None

    def test_fail(self):
        now = datetime.now(timezone.utc)
        p = PhaseExecution(phase="dev", agent="dev", started_at=now)
        p2 = p.fail("Claude API timeout")
        assert p2.status == PhaseStatus.FAILED
        assert p2.summary == "Claude API timeout"


# ── Cycle ────────────────────────────────────────────────────────


class TestCycle:
    def _make_cycle(self) -> Cycle:
        return Cycle(id=CycleId("test123"), project_id="my-project")

    def test_creation(self):
        c = self._make_cycle()
        assert c.status == CycleStatus.PENDING
        assert c.total_tokens == 0
        assert c.current_phase is None
        assert c.duration_seconds is None

    def test_start(self):
        c = self._make_cycle().start(triggered_by="user:jre")
        assert c.status == CycleStatus.RUNNING
        assert c.triggered_by == "user:jre"
        assert c.started_at is not None

    def test_add_phase(self):
        c = self._make_cycle().start()
        now = datetime.now(timezone.utc)
        phase = PhaseExecution(phase="morning", agent="po", started_at=now)
        c2 = c.add_phase(phase)
        assert len(c2.phases) == 1
        assert c2.phases[0].phase == "morning"

    def test_current_phase(self):
        c = self._make_cycle().start()
        now = datetime.now(timezone.utc)
        running = PhaseExecution(phase="dev", agent="dev", started_at=now)
        c2 = c.add_phase(running)
        assert c2.current_phase is not None
        assert c2.current_phase.phase == "dev"

    def test_current_phase_none_when_all_completed(self):
        c = self._make_cycle().start()
        now = datetime.now(timezone.utc)
        completed = PhaseExecution(
            phase="morning", agent="po", started_at=now,
            status=PhaseStatus.COMPLETED, completed_at=now,
        )
        c2 = c.add_phase(completed)
        assert c2.current_phase is None

    def test_add_pr_opened(self):
        c = self._make_cycle().add_pr_opened(42)
        assert 42 in c.prs_opened

    def test_add_pr_merged(self):
        c = self._make_cycle().add_pr_merged(42)
        assert 42 in c.prs_merged

    def test_complete(self):
        c = self._make_cycle().start().complete()
        assert c.status == CycleStatus.COMPLETED
        assert c.completed_at is not None

    def test_fail(self):
        c = self._make_cycle().start().fail()
        assert c.status == CycleStatus.FAILED

    def test_total_tokens(self):
        c = self._make_cycle()
        now = datetime.now(timezone.utc)
        p1 = PhaseExecution(phase="a", agent="po", started_at=now, tokens_used=100)
        p2 = PhaseExecution(phase="b", agent="dev", started_at=now, tokens_used=200)
        c2 = c.add_phase(p1).add_phase(p2)
        assert c2.total_tokens == 300

    def test_get_budget(self):
        c = Cycle(
            id=CycleId("test"), project_id="p",
            budgets=(Budget("dev", 1000, 500), Budget("po", 500, 100)),
        )
        assert c.get_budget("dev") is not None
        assert c.get_budget("dev").used == 500
        assert c.get_budget("missing") is None

    def test_duration_running(self):
        c = self._make_cycle().start()
        assert c.duration_seconds is not None
        assert c.duration_seconds >= 0

    def test_cost_accumulates(self):
        c = self._make_cycle()
        now = datetime.now(timezone.utc)
        p1 = PhaseExecution(phase="a", agent="po", started_at=now, cost_usd=1.50)
        p2 = PhaseExecution(phase="b", agent="dev", started_at=now, cost_usd=2.50)
        c2 = c.add_phase(p1).add_phase(p2)
        assert c2.total_cost_usd == pytest.approx(4.0)


# ── Events ───────────────────────────────────────────────────────


class TestCycleEvents:
    def test_cycle_started(self):
        e = CycleStarted(project_id="p1", triggered_by="manual")
        assert e.project_id == "p1"
        assert e.event_id  # auto-generated
        assert e.occurred_at is not None

    def test_phase_changed(self):
        e = PhaseChanged(phase="development", agent="dev")
        assert e.phase == "development"

    def test_agent_activity(self):
        e = AgentActivity(agent="dev", action="coding", detail="Writing auth.ts")
        assert e.detail == "Writing auth.ts"
        assert e.metadata == {}

    def test_cycle_completed(self):
        e = CycleCompleted(prs_opened=3, prs_merged=2, total_cost_usd=5.0)
        assert e.prs_opened == 3

    def test_cycle_failed(self):
        e = CycleFailed(error="timeout")
        assert e.error == "timeout"

    def test_budget_exceeded(self):
        e = BudgetExceeded(role="dev", used=1500, limit=1000)
        assert e.used == 1500
