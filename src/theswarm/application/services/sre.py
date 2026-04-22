"""Application services for the SRE bounded context (Phase I)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone

from theswarm.domain.sre.entities import CostSample, Deployment, Incident
from theswarm.domain.sre.value_objects import (
    CostSource,
    DeployStatus,
    IncidentSeverity,
    IncidentStatus,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class DeploymentService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def start(
        self, project_id: str, environment: str = "production",
        version: str = "", triggered_by: str = "", notes: str = "",
    ) -> Deployment:
        d = Deployment(
            id=_uid(), project_id=project_id, environment=environment,
            version=version, status=DeployStatus.IN_PROGRESS,
            triggered_by=triggered_by, notes=notes, started_at=_now(),
        )
        return await self._repo.add(d)

    async def succeed(self, deployment_id: str, notes: str = "") -> None:
        await self._repo.update_status(
            deployment_id, DeployStatus.SUCCESS, _now(), notes,
        )

    async def fail(self, deployment_id: str, notes: str = "") -> None:
        await self._repo.update_status(
            deployment_id, DeployStatus.FAILED, _now(), notes,
        )

    async def rollback(self, deployment_id: str, notes: str = "") -> None:
        await self._repo.update_status(
            deployment_id, DeployStatus.ROLLED_BACK, _now(), notes,
        )

    async def list(
        self, project_id: str, limit: int = 20,
    ) -> list[Deployment]:
        return await self._repo.list_for_project(project_id, limit=limit)

    async def get(self, deployment_id: str) -> Deployment | None:
        return await self._repo.get(deployment_id)


class IncidentService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def open(
        self, project_id: str, title: str,
        severity: IncidentSeverity = IncidentSeverity.SEV3,
        summary: str = "",
    ) -> Incident:
        detected = _now()
        first_entry = f"{detected.isoformat()} — detected: {title}"
        i = Incident(
            id=_uid(), project_id=project_id, title=title,
            severity=severity, status=IncidentStatus.OPEN,
            summary=summary, timeline=(first_entry,), detected_at=detected,
        )
        return await self._repo.add(i)

    async def add_timeline(self, incident_id: str, note: str) -> Incident:
        existing = await self._repo.get(incident_id)
        if existing is None:
            raise ValueError(f"Incident {incident_id} not found")
        stamped = f"{_now().isoformat()} — {note}"
        updated = replace(existing, timeline=existing.timeline + (stamped,))
        await self._repo.update(updated)
        return updated

    async def triage(self, incident_id: str, note: str = "") -> Incident:
        existing = await self._repo.get(incident_id)
        if existing is None:
            raise ValueError(f"Incident {incident_id} not found")
        stamped = f"{_now().isoformat()} — triaged: {note}" if note else (
            f"{_now().isoformat()} — triaged"
        )
        updated = replace(
            existing, status=IncidentStatus.TRIAGED,
            timeline=existing.timeline + (stamped,),
        )
        await self._repo.update(updated)
        return updated

    async def mitigate(self, incident_id: str, note: str = "") -> Incident:
        existing = await self._repo.get(incident_id)
        if existing is None:
            raise ValueError(f"Incident {incident_id} not found")
        now = _now()
        stamped = f"{now.isoformat()} — mitigated: {note}" if note else (
            f"{now.isoformat()} — mitigated"
        )
        updated = replace(
            existing, status=IncidentStatus.MITIGATED, mitigated_at=now,
            timeline=existing.timeline + (stamped,),
        )
        await self._repo.update(updated)
        return updated

    async def resolve(self, incident_id: str, note: str = "") -> Incident:
        existing = await self._repo.get(incident_id)
        if existing is None:
            raise ValueError(f"Incident {incident_id} not found")
        now = _now()
        stamped = f"{now.isoformat()} — resolved: {note}" if note else (
            f"{now.isoformat()} — resolved"
        )
        updated = replace(
            existing, status=IncidentStatus.RESOLVED, resolved_at=now,
            timeline=existing.timeline + (stamped,),
        )
        await self._repo.update(updated)
        return updated

    async def write_postmortem(
        self, incident_id: str, postmortem: str,
    ) -> Incident:
        existing = await self._repo.get(incident_id)
        if existing is None:
            raise ValueError(f"Incident {incident_id} not found")
        updated = replace(
            existing, postmortem=postmortem,
            status=IncidentStatus.POSTMORTEM_DONE,
        )
        await self._repo.update(updated)
        return updated

    async def list(
        self, project_id: str, open_only: bool = False,
    ) -> list[Incident]:
        return await self._repo.list_for_project(project_id, open_only=open_only)

    async def get(self, incident_id: str) -> Incident | None:
        return await self._repo.get(incident_id)


class CostService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def record(
        self, project_id: str, source: CostSource, amount_usd: float,
        window: str = "daily", description: str = "",
    ) -> CostSample:
        s = CostSample(
            id=_uid(), project_id=project_id, source=source,
            amount_usd=amount_usd, window=window, description=description,
            created_at=_now(),
        )
        return await self._repo.add(s)

    async def rollup(self, project_id: str) -> dict[str, float]:
        return await self._repo.rollup_by_source(project_id)

    async def list(
        self, project_id: str, limit: int = 100,
    ) -> list[CostSample]:
        return await self._repo.list_for_project(project_id, limit=limit)
