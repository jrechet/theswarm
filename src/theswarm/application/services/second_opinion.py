"""Second-opinion review router.

Given a set of files touched by a PR, the service consults the project's
registered ``CriticalPath`` patterns and decides whether a second reviewer
should be triggered. Dispatch itself (spawning a second reviewer task) is
out of scope for this service — callers do that.
"""

from __future__ import annotations

from dataclasses import dataclass

from theswarm.domain.techlead.entities import CriticalPath
from theswarm.infrastructure.techlead.critical_path_repo import (
    SQLiteCriticalPathRepository,
)


@dataclass(frozen=True)
class SecondOpinionDecision:
    required: bool
    matched_patterns: tuple[str, ...] = ()
    reason: str = ""


class SecondOpinionService:
    def __init__(self, critical_repo: SQLiteCriticalPathRepository) -> None:
        self._critical = critical_repo

    async def evaluate(
        self, project_id: str, files_touched: tuple[str, ...],
    ) -> SecondOpinionDecision:
        paths = await self._critical.list_for_project(project_id)
        if not paths or not files_touched:
            return SecondOpinionDecision(required=False)

        matched: list[str] = []
        reasons: list[str] = []
        for cp in paths:
            if any(cp.matches(f) for f in files_touched):
                matched.append(cp.pattern)
                if cp.reason:
                    reasons.append(cp.reason)

        if not matched:
            return SecondOpinionDecision(required=False)

        return SecondOpinionDecision(
            required=True,
            matched_patterns=tuple(matched),
            reason="; ".join(reasons) or "touches critical path",
        )

    async def add_critical_path(
        self, project_id: str, pattern: str, reason: str = "",
    ) -> CriticalPath:
        path = CriticalPath(
            id=CriticalPath.new_id(),
            project_id=project_id,
            pattern=pattern.strip(),
            reason=reason,
        )
        return await self._critical.add(path)

    async def list_critical_paths(self, project_id: str) -> list[CriticalPath]:
        return await self._critical.list_for_project(project_id)

    async def remove_critical_path(self, path_id: str) -> None:
        await self._critical.delete(path_id)
