"""Application services for the Chief of Staff bounded context (Phase K)."""

from __future__ import annotations

import re
import uuid
from dataclasses import replace
from datetime import datetime, timezone

from theswarm.domain.chief_of_staff.entities import (
    ArchivedProject,
    BudgetPolicy,
    OnboardingStep,
    RoutingRule,
)
from theswarm.domain.chief_of_staff.value_objects import (
    ArchiveReason,
    BudgetState,
    OnboardingStatus,
    RuleStatus,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class RoutingService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def upsert(
        self, pattern: str, target_role: str,
        target_codename: str = "", priority: int = 100,
        status: RuleStatus = RuleStatus.ACTIVE,
    ) -> RoutingRule:
        existing = await self._repo.get_by_pattern(pattern)
        if existing is None:
            r = RoutingRule(
                id=_uid(), pattern=pattern,
                target_role=target_role,
                target_codename=target_codename,
                priority=priority, status=status,
                created_at=_now(),
            )
        else:
            r = replace(
                existing, target_role=target_role,
                target_codename=target_codename,
                priority=priority, status=status,
            )
        return await self._repo.upsert(r)

    async def disable(self, pattern: str) -> RoutingRule:
        existing = await self._repo.get_by_pattern(pattern)
        if existing is None:
            raise ValueError(f"Routing rule not found: {pattern}")
        updated = replace(existing, status=RuleStatus.DISABLED)
        return await self._repo.upsert(updated)

    async def list(self) -> list[RoutingRule]:
        return await self._repo.list_all()

    async def match(self, text: str) -> RoutingRule | None:
        """Return the highest-priority active rule whose pattern hits.

        Pattern is matched case-insensitively as a substring; callers that
        want regex can prefix with ``re:``.
        """
        rules = await self._repo.list_active()
        lowered = text.lower()
        for r in rules:
            pattern = r.pattern
            if pattern.startswith("re:"):
                try:
                    if re.search(pattern[3:], text, re.IGNORECASE):
                        return r
                except re.error:
                    continue
            elif pattern.lower() in lowered:
                return r
        return None


class BudgetPolicyService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def upsert(
        self, project_id: str = "",
        daily_tokens_limit: int = 0,
        daily_cost_usd_limit: float = 0.0,
        state: BudgetState = BudgetState.ACTIVE,
        note: str = "",
    ) -> BudgetPolicy:
        tokens = max(0, daily_tokens_limit)
        cost = max(0.0, daily_cost_usd_limit)
        existing = await self._repo.get_for_project(project_id)
        now = _now()
        if existing is None:
            p = BudgetPolicy(
                id=_uid(), project_id=project_id,
                daily_tokens_limit=tokens,
                daily_cost_usd_limit=cost,
                state=state, note=note,
                created_at=now, updated_at=now,
            )
        else:
            p = replace(
                existing,
                daily_tokens_limit=tokens,
                daily_cost_usd_limit=cost,
                state=state, note=note, updated_at=now,
            )
        return await self._repo.upsert(p)

    async def set_state(
        self, project_id: str, state: BudgetState,
    ) -> BudgetPolicy:
        existing = await self._repo.get_for_project(project_id)
        if existing is None:
            raise ValueError(
                f"Budget policy not found for project: {project_id!r}",
            )
        updated = replace(existing, state=state, updated_at=_now())
        return await self._repo.upsert(updated)

    async def list(self) -> list[BudgetPolicy]:
        return await self._repo.list_all()

    async def get(self, project_id: str = "") -> BudgetPolicy | None:
        return await self._repo.get_for_project(project_id)


class OnboardingService:
    DEFAULT_STEPS: tuple[tuple[str, int], ...] = (
        ("create_roster", 10),
        ("assign_codenames", 20),
        ("seed_memory", 30),
        ("confirm_config", 40),
        ("first_cycle", 50),
    )

    def __init__(self, repo) -> None:
        self._repo = repo

    async def seed_defaults(
        self, project_id: str,
    ) -> list[OnboardingStep]:
        out: list[OnboardingStep] = []
        for name, order in self.DEFAULT_STEPS:
            existing = await self._repo.get_for_step(project_id, name)
            if existing is None:
                step = OnboardingStep(
                    id=_uid(), project_id=project_id, step_name=name,
                    order=order,
                )
                out.append(await self._repo.upsert(step))
            else:
                out.append(existing)
        return out

    async def mark_status(
        self, project_id: str, step_name: str,
        status: OnboardingStatus, note: str = "",
    ) -> OnboardingStep:
        existing = await self._repo.get_for_step(project_id, step_name)
        if existing is None:
            raise ValueError(
                f"Onboarding step not found: {project_id}/{step_name}",
            )
        completed = (
            _now()
            if status in (OnboardingStatus.COMPLETE, OnboardingStatus.SKIPPED)
            else None
        )
        updated = replace(
            existing, status=status, note=note or existing.note,
            completed_at=completed,
        )
        return await self._repo.upsert(updated)

    async def list(self, project_id: str) -> list[OnboardingStep]:
        return await self._repo.list_for_project(project_id)

    async def progress(self, project_id: str) -> tuple[int, int]:
        steps = await self._repo.list_for_project(project_id)
        done = sum(1 for s in steps if s.is_done)
        return (done, len(steps))


class ArchiveService:
    def __init__(self, repo) -> None:
        self._repo = repo

    async def archive(
        self, project_id: str,
        reason: ArchiveReason = ArchiveReason.OTHER,
        memory_frozen: bool = True,
        export_path: str = "", note: str = "",
    ) -> ArchivedProject:
        a = ArchivedProject(
            id=_uid(), project_id=project_id, reason=reason,
            memory_frozen=memory_frozen, export_path=export_path,
            note=note, archived_at=_now(),
        )
        return await self._repo.add(a)

    async def list(self) -> list[ArchivedProject]:
        return await self._repo.list_all()

    async def is_archived(self, project_id: str) -> bool:
        return (await self._repo.get_for_project(project_id)) is not None
