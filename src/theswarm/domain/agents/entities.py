"""Entities for the Agents bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.agents.value_objects import AgentRole, Phase


@dataclass(frozen=True)
class AgentContext:
    """Context loaded before an agent runs — rules, memory, docs."""

    golden_rules: str = ""
    definition_of_done: str = ""
    agent_memory: str = ""
    project_readme: str = ""

    @property
    def is_empty(self) -> bool:
        return not any([self.golden_rules, self.definition_of_done, self.agent_memory])


@dataclass(frozen=True)
class AgentExecution:
    """Record of one agent invocation."""

    role: AgentRole
    phase: Phase
    project_id: str
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    tokens_used: int = 0
    cost_usd: float = 0.0
    result_summary: str = ""
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.error is None and self.completed_at is not None

    @property
    def duration_seconds(self) -> float | None:
        if not self.completed_at:
            return None
        return (self.completed_at - self.started_at).total_seconds()

    def complete(self, summary: str, tokens: int = 0, cost: float = 0.0) -> AgentExecution:
        return AgentExecution(
            role=self.role,
            phase=self.phase,
            project_id=self.project_id,
            started_at=self.started_at,
            completed_at=datetime.now(timezone.utc),
            tokens_used=tokens,
            cost_usd=cost,
            result_summary=summary,
        )

    def fail(self, error: str) -> AgentExecution:
        return AgentExecution(
            role=self.role,
            phase=self.phase,
            project_id=self.project_id,
            started_at=self.started_at,
            completed_at=datetime.now(timezone.utc),
            tokens_used=self.tokens_used,
            cost_usd=self.cost_usd,
            error=error,
        )
