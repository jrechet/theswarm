"""Application services for the Architect bounded context (Phase K)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone

from theswarm.domain.architect.entities import (
    DirectionBrief,
    PavedRoadRule,
    PortfolioADR,
)
from theswarm.domain.architect.value_objects import (
    ADRStatus,
    BriefScope,
    RuleSeverity,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class PavedRoadService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def upsert(
        self, name: str, rule: str, rationale: str = "",
        severity: RuleSeverity = RuleSeverity.ADVISORY,
        tags: tuple[str, ...] = (),
    ) -> PavedRoadRule:
        existing = await self._repo.get_for_name(name)
        now = _now()
        if existing is None:
            r = PavedRoadRule(
                id=_uid(), name=name, rule=rule, rationale=rationale,
                severity=severity, tags=tags,
                created_at=now, updated_at=now,
            )
        else:
            r = replace(
                existing, rule=rule, rationale=rationale,
                severity=severity, tags=tags, updated_at=now,
            )
        return await self._repo.upsert(r)

    async def list(self) -> list[PavedRoadRule]:
        return await self._repo.list_all()


class PortfolioADRService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def propose(
        self, title: str, context: str = "", decision: str = "",
        consequences: str = "", project_id: str = "",
    ) -> PortfolioADR:
        now = _now()
        a = PortfolioADR(
            id=_uid(), title=title, status=ADRStatus.PROPOSED,
            context=context, decision=decision, consequences=consequences,
            project_id=project_id, created_at=now, updated_at=now,
        )
        return await self._repo.add(a)

    async def accept(self, adr_id: str) -> PortfolioADR:
        existing = await self._repo.get_by_id(adr_id)
        if existing is None:
            raise ValueError(f"ADR not found: {adr_id}")
        updated = replace(
            existing, status=ADRStatus.ACCEPTED, updated_at=_now(),
        )
        return await self._repo.update(updated)

    async def reject(self, adr_id: str) -> PortfolioADR:
        existing = await self._repo.get_by_id(adr_id)
        if existing is None:
            raise ValueError(f"ADR not found: {adr_id}")
        updated = replace(
            existing, status=ADRStatus.REJECTED, updated_at=_now(),
        )
        return await self._repo.update(updated)

    async def supersede(
        self, old_adr_id: str, new_adr_id: str,
    ) -> PortfolioADR:
        existing = await self._repo.get_by_id(old_adr_id)
        if existing is None:
            raise ValueError(f"ADR not found: {old_adr_id}")
        updated = replace(
            existing, status=ADRStatus.SUPERSEDED,
            supersedes=new_adr_id, updated_at=_now(),
        )
        return await self._repo.update(updated)

    async def list(
        self, project_id: str | None = None,
    ) -> list[PortfolioADR]:
        return await self._repo.list_all(project_id=project_id)


class DirectionBriefService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def record(
        self, title: str,
        scope: BriefScope = BriefScope.PORTFOLIO,
        project_id: str = "", period: str = "", author: str = "",
        focus_areas: tuple[str, ...] = (),
        risks: tuple[str, ...] = (),
        narrative: str = "",
    ) -> DirectionBrief:
        b = DirectionBrief(
            id=_uid(), title=title, scope=scope,
            project_id=project_id if scope == BriefScope.PROJECT else "",
            period=period, author=author,
            focus_areas=focus_areas, risks=risks, narrative=narrative,
            created_at=_now(),
        )
        return await self._repo.add(b)

    async def list_portfolio(self) -> list[DirectionBrief]:
        return await self._repo.list_portfolio()

    async def list_for_project(
        self, project_id: str,
    ) -> list[DirectionBrief]:
        return await self._repo.list_for_project(project_id)
