"""Application services for the Security bounded context (Phase I)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone

from theswarm.domain.security.entities import (
    AuthZRule,
    DataInventoryEntry,
    SBOMArtifact,
    SecurityFinding,
    ThreatModel,
)
from theswarm.domain.security.value_objects import (
    AuthZEffect,
    DataClass,
    FindingSeverity,
    FindingStatus,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class ThreatModelService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def upsert(
        self, project_id: str, title: str, assets: str = "",
        actors: str = "", trust_boundaries: str = "", stride_notes: str = "",
    ) -> ThreatModel:
        existing = await self._repo.get_for_project(project_id)
        now = _now()
        if existing is None:
            tm = ThreatModel(
                id=_uid(), project_id=project_id, title=title,
                assets=assets, actors=actors,
                trust_boundaries=trust_boundaries, stride_notes=stride_notes,
                created_at=now, updated_at=now,
            )
        else:
            tm = replace(
                existing, title=title, assets=assets, actors=actors,
                trust_boundaries=trust_boundaries, stride_notes=stride_notes,
                updated_at=now,
            )
        return await self._repo.upsert(tm)

    async def get(self, project_id: str) -> ThreatModel | None:
        return await self._repo.get_for_project(project_id)


class DataInventoryService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def upsert(
        self, project_id: str, field_name: str, classification: DataClass,
        storage_notes: str = "", notes: str = "",
    ) -> DataInventoryEntry:
        existing = await self._repo.get_for_field(project_id, field_name)
        now = _now()
        if existing is None:
            e = DataInventoryEntry(
                id=_uid(), project_id=project_id, field_name=field_name,
                classification=classification, storage_notes=storage_notes,
                notes=notes, created_at=now, updated_at=now,
            )
        else:
            e = replace(
                existing, classification=classification,
                storage_notes=storage_notes, notes=notes, updated_at=now,
            )
        return await self._repo.upsert(e)

    async def list(self, project_id: str) -> list[DataInventoryEntry]:
        return await self._repo.list_for_project(project_id)


class SecurityFindingService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def open(
        self, project_id: str, severity: FindingSeverity, title: str,
        description: str = "", cve: str = "",
    ) -> SecurityFinding:
        f = SecurityFinding(
            id=_uid(), project_id=project_id, severity=severity,
            title=title, description=description, cve=cve,
            status=FindingStatus.OPEN, created_at=_now(),
        )
        return await self._repo.add(f)

    async def triage(self, finding_id: str, note: str = "") -> None:
        await self._repo.update_status(
            finding_id, FindingStatus.TRIAGED, note, None,
        )

    async def resolve(self, finding_id: str, note: str = "") -> None:
        await self._repo.update_status(
            finding_id, FindingStatus.RESOLVED, note, _now(),
        )

    async def suppress(self, finding_id: str, note: str = "") -> None:
        await self._repo.update_status(
            finding_id, FindingStatus.SUPPRESSED, note, _now(),
        )

    async def list(
        self, project_id: str, open_only: bool = False,
    ) -> list[SecurityFinding]:
        return await self._repo.list_for_project(project_id, open_only=open_only)


class SBOMService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def record(
        self, project_id: str, tool: str = "syft", cycle_id: str = "",
        package_count: int = 0, license_summary: str = "",
        artifact_path: str = "",
    ) -> SBOMArtifact:
        a = SBOMArtifact(
            id=_uid(), project_id=project_id, cycle_id=cycle_id, tool=tool,
            package_count=package_count, license_summary=license_summary,
            artifact_path=artifact_path, created_at=_now(),
        )
        return await self._repo.add(a)

    async def latest(self, project_id: str) -> SBOMArtifact | None:
        return await self._repo.latest_for_project(project_id)

    async def list(self, project_id: str) -> list[SBOMArtifact]:
        return await self._repo.list_for_project(project_id)


class AuthZService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def upsert(
        self, project_id: str, actor_role: str, resource: str, action: str,
        effect: AuthZEffect = AuthZEffect.ALLOW, notes: str = "",
    ) -> AuthZRule:
        existing = await self._repo.get_for_key(
            project_id, actor_role, resource, action,
        )
        now = _now()
        if existing is None:
            rule = AuthZRule(
                id=_uid(), project_id=project_id, actor_role=actor_role,
                resource=resource, action=action, effect=effect, notes=notes,
                created_at=now, updated_at=now,
            )
        else:
            rule = replace(existing, effect=effect, notes=notes, updated_at=now)
        return await self._repo.upsert(rule)

    async def list(self, project_id: str) -> list[AuthZRule]:
        return await self._repo.list_for_project(project_id)

    async def delete(self, rule_id: str) -> None:
        await self._repo.delete(rule_id)
