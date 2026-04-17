"""Entities for the Cycles bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.cycles.value_objects import (
    Budget,
    CycleId,
    CycleStatus,
    PhaseStatus,
    TokenUsage,
)


@dataclass(frozen=True)
class PhaseExecution:
    """Record of one phase within a cycle."""

    phase: str
    agent: str
    started_at: datetime
    completed_at: datetime | None = None
    status: PhaseStatus = PhaseStatus.RUNNING
    tokens_used: int = 0
    cost_usd: float = 0.0
    summary: str = ""

    @property
    def duration_seconds(self) -> float | None:
        """Wall-clock runtime of the phase, or None if not yet started."""
        if self.started_at is None:
            return None
        end = self.completed_at or datetime.now(timezone.utc)
        return max(0.0, (end - self.started_at).total_seconds())

    @property
    def start_time_display(self) -> str:
        """HH:MM:SS label for the start timestamp."""
        return self.started_at.strftime("%H:%M:%S") if self.started_at else ""

    def complete(self, summary: str, tokens: int = 0, cost: float = 0.0) -> PhaseExecution:
        return PhaseExecution(
            phase=self.phase,
            agent=self.agent,
            started_at=self.started_at,
            completed_at=datetime.now(timezone.utc),
            status=PhaseStatus.COMPLETED,
            tokens_used=tokens,
            cost_usd=cost,
            summary=summary,
        )

    def fail(self, summary: str) -> PhaseExecution:
        return PhaseExecution(
            phase=self.phase,
            agent=self.agent,
            started_at=self.started_at,
            completed_at=datetime.now(timezone.utc),
            status=PhaseStatus.FAILED,
            tokens_used=self.tokens_used,
            cost_usd=self.cost_usd,
            summary=summary,
        )


@dataclass(frozen=True)
class Cycle:
    """A single execution cycle for a project."""

    id: CycleId
    project_id: str
    status: CycleStatus = CycleStatus.PENDING
    triggered_by: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    phases: tuple[PhaseExecution, ...] = ()
    budgets: tuple[Budget, ...] = ()
    total_cost_usd: float = 0.0
    prs_opened: tuple[int, ...] = ()
    prs_merged: tuple[int, ...] = ()

    @property
    def total_tokens(self) -> int:
        return sum(p.tokens_used for p in self.phases)

    @property
    def current_phase(self) -> PhaseExecution | None:
        for p in reversed(self.phases):
            if p.status == PhaseStatus.RUNNING:
                return p
        return None

    @property
    def duration_seconds(self) -> float | None:
        if not self.started_at:
            return None
        end = self.completed_at or datetime.now(timezone.utc)
        return (end - self.started_at).total_seconds()

    def start(self, triggered_by: str = "") -> Cycle:
        return Cycle(
            id=self.id,
            project_id=self.project_id,
            status=CycleStatus.RUNNING,
            triggered_by=triggered_by,
            started_at=datetime.now(timezone.utc),
            phases=self.phases,
            budgets=self.budgets,
        )

    def add_phase(self, phase: PhaseExecution) -> Cycle:
        return Cycle(
            id=self.id,
            project_id=self.project_id,
            status=self.status,
            triggered_by=self.triggered_by,
            started_at=self.started_at,
            completed_at=self.completed_at,
            phases=self.phases + (phase,),
            budgets=self.budgets,
            total_cost_usd=self.total_cost_usd + phase.cost_usd,
            prs_opened=self.prs_opened,
            prs_merged=self.prs_merged,
        )

    def add_pr_opened(self, pr_number: int) -> Cycle:
        return Cycle(
            id=self.id,
            project_id=self.project_id,
            status=self.status,
            triggered_by=self.triggered_by,
            started_at=self.started_at,
            completed_at=self.completed_at,
            phases=self.phases,
            budgets=self.budgets,
            total_cost_usd=self.total_cost_usd,
            prs_opened=self.prs_opened + (pr_number,),
            prs_merged=self.prs_merged,
        )

    def add_pr_merged(self, pr_number: int) -> Cycle:
        return Cycle(
            id=self.id,
            project_id=self.project_id,
            status=self.status,
            triggered_by=self.triggered_by,
            started_at=self.started_at,
            completed_at=self.completed_at,
            phases=self.phases,
            budgets=self.budgets,
            total_cost_usd=self.total_cost_usd,
            prs_opened=self.prs_opened,
            prs_merged=self.prs_merged + (pr_number,),
        )

    def complete(self) -> Cycle:
        return Cycle(
            id=self.id,
            project_id=self.project_id,
            status=CycleStatus.COMPLETED,
            triggered_by=self.triggered_by,
            started_at=self.started_at,
            completed_at=datetime.now(timezone.utc),
            phases=self.phases,
            budgets=self.budgets,
            total_cost_usd=self.total_cost_usd,
            prs_opened=self.prs_opened,
            prs_merged=self.prs_merged,
        )

    def fail(self) -> Cycle:
        return Cycle(
            id=self.id,
            project_id=self.project_id,
            status=CycleStatus.FAILED,
            triggered_by=self.triggered_by,
            started_at=self.started_at,
            completed_at=datetime.now(timezone.utc),
            phases=self.phases,
            budgets=self.budgets,
            total_cost_usd=self.total_cost_usd,
            prs_opened=self.prs_opened,
            prs_merged=self.prs_merged,
        )

    def get_budget(self, role: str) -> Budget | None:
        for b in self.budgets:
            if b.role == role:
                return b
        return None
