"""Tests for domain/cycles — 100% coverage target."""

from __future__ import annotations

import dataclasses
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

    def test_duration_seconds_completed(self):
        from datetime import timedelta
        start = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(seconds=42.5)
        p = PhaseExecution(
            phase="dev", agent="dev",
            started_at=start, completed_at=end,
        )
        assert p.duration_seconds == 42.5

    def test_duration_seconds_still_running_is_nonnegative(self):
        now = datetime.now(timezone.utc)
        p = PhaseExecution(phase="dev", agent="dev", started_at=now)
        d = p.duration_seconds
        assert d is not None
        assert d >= 0


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


# ── Cycle transitions keep what they do not own ─────────────────
#
# Each transition used to rebuild the Cycle field by field and forgot
# trace_id and resumed_as: the first PhaseChanged saved the row with ""
# and the theater lost its trace link. Every field is set here, so a
# field added to Cycle later fails this test until it is listed.

_T0 = datetime(2026, 9, 24, 8, 0, tzinfo=timezone.utc)


def _cycle_with_every_field_set() -> Cycle:
    return Cycle(
        id=CycleId("c-all"),
        project_id="o/r",
        status=CycleStatus.RUNNING,
        triggered_by="web",
        started_at=_T0,
        completed_at=_T0,
        phases=(PhaseExecution(phase="po_morning", agent="po", started_at=_T0),),
        budgets=(Budget("dev", 1000, 10),),
        total_cost_usd=1.5,
        prs_opened=(7,),
        prs_merged=(7,),
        trace_id="a" * 32,
        resumed_as="next-cycle",
    )


_PHASE = PhaseExecution(phase="dev_iter", agent="dev", started_at=_T0, cost_usd=0.5)

_TRANSITIONS = {
    "start": (lambda c: c.start("api"), {"status", "triggered_by", "started_at", "completed_at"}),
    "add_phase": (lambda c: c.add_phase(_PHASE), {"phases", "total_cost_usd"}),
    "add_pr_opened": (lambda c: c.add_pr_opened(8), {"prs_opened"}),
    "add_pr_merged": (lambda c: c.add_pr_merged(8), {"prs_merged"}),
    "complete": (lambda c: c.complete(), {"status", "completed_at"}),
    "fail": (lambda c: c.fail(), {"status", "completed_at"}),
    "cancel": (lambda c: c.cancel(), {"status", "completed_at"}),
}


def test_the_fixture_sets_every_field_of_cycle():
    cycle = _cycle_with_every_field_set()
    for f in dataclasses.fields(Cycle):
        if f.default is not dataclasses.MISSING:
            assert getattr(cycle, f.name) != f.default, f"{f.name} left at its default"


@pytest.mark.parametrize("name", sorted(_TRANSITIONS))
def test_a_transition_keeps_every_field_it_does_not_own(name):
    transition, owned = _TRANSITIONS[name]
    before = _cycle_with_every_field_set()

    after = transition(before)

    kept = {f.name for f in dataclasses.fields(Cycle)} - owned
    assert {k: getattr(after, k) for k in kept} == {k: getattr(before, k) for k in kept}


def test_start_clears_the_end_of_an_earlier_run():
    c = _cycle_with_every_field_set().start("api")
    assert c.completed_at is None
    assert c.trace_id == "a" * 32


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
