"""Thin orchestrator over the debt register."""

from __future__ import annotations

from theswarm.domain.techlead.entities import DebtEntry
from theswarm.domain.techlead.value_objects import DebtSeverity
from theswarm.infrastructure.techlead.debt_repo import SQLiteDebtRepository


class DebtService:
    def __init__(self, debt_repo: SQLiteDebtRepository) -> None:
        self._debt = debt_repo

    async def add(
        self,
        *,
        project_id: str,
        title: str,
        severity: DebtSeverity = DebtSeverity.MEDIUM,
        blast_radius: str = "",
        location: str = "",
        owner_codename: str = "",
        description: str = "",
    ) -> DebtEntry:
        entry = DebtEntry(
            id=DebtEntry.new_id(),
            project_id=project_id,
            title=title.strip(),
            severity=severity,
            blast_radius=blast_radius,
            location=location,
            owner_codename=owner_codename,
            description=description,
        )
        return await self._debt.create(entry)

    async def resolve(self, debt_id: str) -> DebtEntry | None:
        return await self._debt.resolve(debt_id)

    async def delete(self, debt_id: str) -> None:
        await self._debt.delete(debt_id)

    async def list(
        self, project_id: str, *, include_resolved: bool = False,
    ) -> list[DebtEntry]:
        return await self._debt.list_for_project(
            project_id, include_resolved=include_resolved,
        )
