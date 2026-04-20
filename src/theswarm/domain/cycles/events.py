"""Domain events for the Cycles bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field

from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.events import DomainEvent


@dataclass(frozen=True)
class CycleStarted(DomainEvent):
    cycle_id: CycleId = field(default_factory=CycleId.generate)
    project_id: str = ""
    triggered_by: str = ""


@dataclass(frozen=True)
class PhaseChanged(DomainEvent):
    cycle_id: CycleId = field(default_factory=CycleId.generate)
    project_id: str = ""
    phase: str = ""
    agent: str = ""


@dataclass(frozen=True)
class AgentActivity(DomainEvent):
    cycle_id: CycleId = field(default_factory=CycleId.generate)
    project_id: str = ""
    agent: str = ""
    action: str = ""
    detail: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AgentThought(DomainEvent):
    """Sprint D V3 — an agent's reasoning step (narrative/thinking text)."""

    cycle_id: CycleId = field(default_factory=CycleId.generate)
    project_id: str = ""
    agent: str = ""
    thought: str = ""
    phase: str = ""


@dataclass(frozen=True)
class AgentStep(DomainEvent):
    """Sprint D V3 — a discrete action the agent is taking (tool call, stage)."""

    cycle_id: CycleId = field(default_factory=CycleId.generate)
    project_id: str = ""
    agent: str = ""
    step: str = ""
    detail: str = ""
    phase: str = ""


@dataclass(frozen=True)
class CycleCompleted(DomainEvent):
    cycle_id: CycleId = field(default_factory=CycleId.generate)
    project_id: str = ""
    total_cost_usd: float = 0.0
    prs_opened: int = 0
    prs_merged: int = 0
    report_id: str = ""


@dataclass(frozen=True)
class CycleFailed(DomainEvent):
    cycle_id: CycleId = field(default_factory=CycleId.generate)
    project_id: str = ""
    error: str = ""


@dataclass(frozen=True)
class BudgetExceeded(DomainEvent):
    cycle_id: CycleId = field(default_factory=CycleId.generate)
    project_id: str = ""
    role: str = ""
    used: int = 0
    limit: int = 0


@dataclass(frozen=True)
class CycleBlocked(DomainEvent):
    """A cycle could not start because a cap was hit or the project is paused."""

    project_id: str = ""
    reason: str = ""
