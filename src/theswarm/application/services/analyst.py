"""Application services for the Analyst bounded context (Phase J)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone

from theswarm.domain.analyst.entities import (
    InstrumentationPlan,
    MetricDefinition,
    OutcomeObservation,
)
from theswarm.domain.analyst.value_objects import (
    InstrumentationStatus,
    MetricKind,
    OutcomeDirection,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class MetricDefinitionService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def upsert(
        self, project_id: str, name: str, kind: MetricKind,
        unit: str = "", definition: str = "", owner: str = "",
        target: str = "",
    ) -> MetricDefinition:
        existing = await self._repo.get_for_name(project_id, name)
        now = _now()
        if existing is None:
            m = MetricDefinition(
                id=_uid(), project_id=project_id, name=name, kind=kind,
                unit=unit, definition=definition, owner=owner, target=target,
                created_at=now, updated_at=now,
            )
        else:
            m = replace(
                existing, kind=kind, unit=unit, definition=definition,
                owner=owner, target=target, updated_at=now,
            )
        return await self._repo.upsert(m)

    async def list(self, project_id: str) -> list[MetricDefinition]:
        return await self._repo.list_for_project(project_id)


class InstrumentationPlanService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def upsert(
        self, project_id: str, story_id: str, metric_name: str,
        hypothesis: str = "", method: str = "",
        status: InstrumentationStatus = InstrumentationStatus.PROPOSED,
        note: str = "",
    ) -> InstrumentationPlan:
        existing = await self._repo.get_for_key(
            project_id, story_id, metric_name,
        )
        now = _now()
        if existing is None:
            p = InstrumentationPlan(
                id=_uid(), project_id=project_id, story_id=story_id,
                metric_name=metric_name, hypothesis=hypothesis,
                method=method, status=status, note=note,
                created_at=now, updated_at=now,
            )
        else:
            p = replace(
                existing, hypothesis=hypothesis, method=method,
                status=status, note=note, updated_at=now,
            )
        return await self._repo.upsert(p)

    async def mark_status(
        self, project_id: str, story_id: str, metric_name: str,
        status: InstrumentationStatus, note: str = "",
    ) -> InstrumentationPlan:
        existing = await self._repo.get_for_key(
            project_id, story_id, metric_name,
        )
        if existing is None:
            raise ValueError(
                f"Plan not found: {project_id}/{story_id}/{metric_name}",
            )
        updated = replace(
            existing, status=status,
            note=note or existing.note, updated_at=_now(),
        )
        return await self._repo.upsert(updated)

    async def list(
        self, project_id: str, missing_only: bool = False,
    ) -> list[InstrumentationPlan]:
        return await self._repo.list_for_project(
            project_id, missing_only=missing_only,
        )


class OutcomeObservationService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def record(
        self, project_id: str, story_id: str, metric_name: str,
        baseline: str = "", observed: str = "",
        direction: OutcomeDirection = OutcomeDirection.INCONCLUSIVE,
        window: str = "", note: str = "",
    ) -> OutcomeObservation:
        o = OutcomeObservation(
            id=_uid(), project_id=project_id, story_id=story_id,
            metric_name=metric_name, baseline=baseline, observed=observed,
            direction=direction, window=window, note=note, created_at=_now(),
        )
        return await self._repo.add(o)

    async def list(self, project_id: str) -> list[OutcomeObservation]:
        return await self._repo.list_for_project(project_id)

    async def list_for_story(
        self, project_id: str, story_id: str,
    ) -> list[OutcomeObservation]:
        return await self._repo.list_for_story(project_id, story_id)
