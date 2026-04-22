"""Service for ADR creation and light editing."""

from __future__ import annotations

from theswarm.domain.techlead.entities import ADR
from theswarm.domain.techlead.value_objects import ADRStatus
from theswarm.infrastructure.techlead.adr_repo import SQLiteADRRepository


class ADRService:
    """Creates, updates, and lists Architecture Decision Records."""

    def __init__(self, adr_repo: SQLiteADRRepository) -> None:
        self._adrs = adr_repo

    async def propose(
        self,
        *,
        project_id: str,
        title: str,
        context: str = "",
        decision: str = "",
        consequences: str = "",
        tags: tuple[str, ...] = (),
    ) -> ADR:
        number = await self._adrs.next_number(project_id)
        adr = ADR(
            id=ADR.new_id(),
            project_id=project_id,
            number=number,
            title=title.strip() or f"ADR-{number}",
            status=ADRStatus.PROPOSED,
            context=context,
            decision=decision,
            consequences=consequences,
            tags=tags,
        )
        return await self._adrs.create(adr)

    async def accept(self, adr_id: str) -> ADR | None:
        return await self._adrs.set_status(adr_id, ADRStatus.ACCEPTED)

    async def reject(self, adr_id: str) -> ADR | None:
        return await self._adrs.set_status(adr_id, ADRStatus.REJECTED)

    async def supersede(self, old_id: str, new_id: str) -> ADR | None:
        new_adr = await self._adrs.get(new_id)
        if new_adr is None:
            return None
        await self._adrs.update(
            ADR(
                id=new_adr.id,
                project_id=new_adr.project_id,
                number=new_adr.number,
                title=new_adr.title,
                status=new_adr.status,
                context=new_adr.context,
                decision=new_adr.decision,
                consequences=new_adr.consequences,
                supersedes=old_id,
                tags=new_adr.tags,
                created_at=new_adr.created_at,
                updated_at=new_adr.updated_at,
            ),
        )
        return await self._adrs.set_status(old_id, ADRStatus.SUPERSEDED)

    async def list(self, project_id: str) -> list[ADR]:
        return await self._adrs.list_for_project(project_id)
