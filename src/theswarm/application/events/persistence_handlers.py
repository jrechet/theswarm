"""Event handlers that persist cycle and activity data to SQLite.

Subscribed to the EventBus so that every domain event from the
ProgressBridge (or any other publisher) is durably stored.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from theswarm.domain.cycles.entities import Cycle, PhaseExecution
from theswarm.domain.cycles.events import (
    AgentActivity,
    CycleCompleted,
    CycleFailed,
    CycleStarted,
    PhaseChanged,
)
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus, PhaseStatus
from theswarm.domain.events import DomainEvent

log = logging.getLogger(__name__)


class CyclePersistenceHandler:
    """Persist cycle lifecycle events to SQLite."""

    def __init__(self, cycle_repo: object) -> None:
        self._cycle_repo = cycle_repo

    async def handle(self, event: DomainEvent) -> None:
        if isinstance(event, CycleStarted):
            await self._on_started(event)
        elif isinstance(event, PhaseChanged):
            await self._on_phase_changed(event)
        elif isinstance(event, CycleCompleted):
            await self._on_completed(event)
        elif isinstance(event, CycleFailed):
            await self._on_failed(event)

    async def _on_started(self, event: CycleStarted) -> None:
        try:
            cycle = Cycle(
                id=event.cycle_id,
                project_id=event.project_id,
                status=CycleStatus.RUNNING,
                triggered_by=event.triggered_by,
                started_at=event.occurred_at,
            )
            await self._cycle_repo.save(cycle)
        except Exception:
            log.exception("Failed to persist CycleStarted %s", event.cycle_id)

    async def _on_phase_changed(self, event: PhaseChanged) -> None:
        try:
            cycle = await self._cycle_repo.get(event.cycle_id)
            if cycle is None:
                return
            phase = PhaseExecution(
                phase=event.phase,
                agent=event.agent,
                started_at=event.occurred_at,
                status=PhaseStatus.RUNNING,
            )
            cycle = cycle.add_phase(phase)
            # Mark previous phase as completed
            if len(cycle.phases) >= 2:
                prev = cycle.phases[-2]
                if prev.status == PhaseStatus.RUNNING:
                    completed_prev = prev.complete(summary="")
                    phases = list(cycle.phases)
                    phases[-2] = completed_prev
                    cycle = Cycle(
                        id=cycle.id,
                        project_id=cycle.project_id,
                        status=cycle.status,
                        triggered_by=cycle.triggered_by,
                        started_at=cycle.started_at,
                        completed_at=cycle.completed_at,
                        phases=tuple(phases),
                        budgets=cycle.budgets,
                        total_cost_usd=cycle.total_cost_usd,
                        prs_opened=cycle.prs_opened,
                        prs_merged=cycle.prs_merged,
                    )
            await self._cycle_repo.save(cycle)
        except Exception:
            log.exception("Failed to persist PhaseChanged %s", event.cycle_id)

    async def _on_completed(self, event: CycleCompleted) -> None:
        try:
            cycle = await self._cycle_repo.get(event.cycle_id)
            if cycle is None:
                return
            # Complete the last running phase
            phases = list(cycle.phases)
            if phases and phases[-1].status == PhaseStatus.RUNNING:
                phases[-1] = phases[-1].complete(summary="Cycle completed")
            cycle = Cycle(
                id=cycle.id,
                project_id=cycle.project_id,
                status=CycleStatus.COMPLETED,
                triggered_by=cycle.triggered_by,
                started_at=cycle.started_at,
                completed_at=event.occurred_at,
                phases=tuple(phases),
                budgets=cycle.budgets,
                total_cost_usd=event.total_cost_usd,
                prs_opened=tuple(range(1, event.prs_opened + 1)) if event.prs_opened else cycle.prs_opened,
                prs_merged=tuple(range(1, event.prs_merged + 1)) if event.prs_merged else cycle.prs_merged,
            )
            await self._cycle_repo.save(cycle)
        except Exception:
            log.exception("Failed to persist CycleCompleted %s", event.cycle_id)

    async def _on_failed(self, event: CycleFailed) -> None:
        try:
            cycle = await self._cycle_repo.get(event.cycle_id)
            if cycle is None:
                return
            # Fail the last running phase
            phases = list(cycle.phases)
            if phases and phases[-1].status == PhaseStatus.RUNNING:
                phases[-1] = phases[-1].fail(summary=event.error[:200])
            cycle = Cycle(
                id=cycle.id,
                project_id=cycle.project_id,
                status=CycleStatus.FAILED,
                triggered_by=cycle.triggered_by,
                started_at=cycle.started_at,
                completed_at=event.occurred_at,
                phases=tuple(phases),
                budgets=cycle.budgets,
                total_cost_usd=cycle.total_cost_usd,
                prs_opened=cycle.prs_opened,
                prs_merged=cycle.prs_merged,
            )
            await self._cycle_repo.save(cycle)
        except Exception:
            log.exception("Failed to persist CycleFailed %s", event.cycle_id)


class ActivityPersistenceHandler:
    """Persist AgentActivity events to the activities table."""

    def __init__(self, activity_repo: object) -> None:
        self._activity_repo = activity_repo

    async def handle(self, event: DomainEvent) -> None:
        if not isinstance(event, AgentActivity):
            return
        try:
            await self._activity_repo.save(
                cycle_id=str(event.cycle_id),
                project_id=event.project_id,
                agent=event.agent,
                action=event.action,
                detail=event.detail,
                metadata=event.metadata,
            )
        except Exception:
            log.exception("Failed to persist AgentActivity")
