"""Application services for the Designer bounded context (Phase H)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from theswarm.domain.designer.entities import (
    AntiTemplateCheck,
    ComponentEntry,
    DesignBrief,
    DesignToken,
    VisualRegression,
)
from theswarm.domain.designer.value_objects import (
    BriefStatus,
    CheckStatus,
    ComponentStatus,
    TokenKind,
)
from theswarm.infrastructure.designer import (
    SQLiteAntiTemplateRepository,
    SQLiteComponentRepository,
    SQLiteDesignBriefRepository,
    SQLiteDesignTokenRepository,
    SQLiteVisualRegressionRepository,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DesignSystemService:
    """Custody of per-project design tokens (colour, type, spacing, motion)."""

    def __init__(self, repo: SQLiteDesignTokenRepository) -> None:
        self._repo = repo

    async def set_token(
        self,
        *,
        project_id: str,
        name: str,
        kind: TokenKind = TokenKind.OTHER,
        value: str = "",
        notes: str = "",
    ) -> DesignToken:
        existing = await self._repo.get_for_name(project_id, name)
        token = DesignToken(
            id=existing.id if existing else DesignToken.new_id(),
            project_id=project_id,
            name=name,
            kind=kind,
            value=value,
            notes=notes or (existing.notes if existing else ""),
            created_at=existing.created_at if existing else _now(),
            updated_at=_now(),
        )
        return await self._repo.upsert(token)

    async def list_tokens(self, project_id: str) -> list[DesignToken]:
        return await self._repo.list_for_project(project_id)

    async def get_token(
        self, project_id: str, name: str,
    ) -> DesignToken | None:
        return await self._repo.get_for_name(project_id, name)

    async def delete_token(self, token_id: str) -> None:
        await self._repo.delete(token_id)


class ComponentInventoryService:
    """Track components; promote/deprecate; bump usage counts."""

    def __init__(self, repo: SQLiteComponentRepository) -> None:
        self._repo = repo

    async def register(
        self,
        *,
        project_id: str,
        name: str,
        status: ComponentStatus = ComponentStatus.PROPOSED,
        path: str = "",
        notes: str = "",
    ) -> ComponentEntry:
        existing = await self._repo.get_for_name(project_id, name)
        entry = ComponentEntry(
            id=existing.id if existing else ComponentEntry.new_id(),
            project_id=project_id,
            name=name,
            status=status,
            path=path or (existing.path if existing else ""),
            usage_count=existing.usage_count if existing else 0,
            notes=notes or (existing.notes if existing else ""),
            created_at=existing.created_at if existing else _now(),
            updated_at=_now(),
        )
        return await self._repo.upsert(entry)

    async def promote(
        self, *, project_id: str, name: str,
    ) -> ComponentEntry | None:
        existing = await self._repo.get_for_name(project_id, name)
        if existing is None:
            return None
        updated = replace(
            existing, status=ComponentStatus.SHARED, updated_at=_now(),
        )
        return await self._repo.upsert(updated)

    async def deprecate(
        self, *, project_id: str, name: str,
    ) -> ComponentEntry | None:
        existing = await self._repo.get_for_name(project_id, name)
        if existing is None:
            return None
        updated = replace(
            existing, status=ComponentStatus.DEPRECATED, updated_at=_now(),
        )
        return await self._repo.upsert(updated)

    async def bump_usage(
        self, *, project_id: str, name: str, delta: int = 1,
    ) -> ComponentEntry | None:
        existing = await self._repo.get_for_name(project_id, name)
        if existing is None:
            return None
        updated = replace(
            existing,
            usage_count=max(0, existing.usage_count + delta),
            updated_at=_now(),
        )
        return await self._repo.upsert(updated)

    async def list_inventory(
        self, project_id: str, *, active_only: bool = False,
    ) -> list[ComponentEntry]:
        return await self._repo.list_for_project(
            project_id, active_only=active_only,
        )


class DesignBriefService:
    """Lightweight design brief per UI story; gates Dev until READY/APPROVED."""

    def __init__(self, repo: SQLiteDesignBriefRepository) -> None:
        self._repo = repo

    async def draft(
        self,
        *,
        project_id: str,
        story_id: str,
        title: str = "",
        intent: str = "",
        hierarchy: str = "",
        states: str = "",
        motion: str = "",
        reference_url: str = "",
    ) -> DesignBrief:
        existing = await self._repo.get_for_story(project_id, story_id)
        brief = DesignBrief(
            id=existing.id if existing else DesignBrief.new_id(),
            project_id=project_id,
            story_id=story_id,
            title=title,
            intent=intent,
            hierarchy=hierarchy,
            states=states,
            motion=motion,
            reference_url=reference_url,
            status=existing.status if existing else BriefStatus.DRAFT,
            approval_note=existing.approval_note if existing else "",
            created_at=existing.created_at if existing else _now(),
            updated_at=_now(),
        )
        return await self._repo.upsert(brief)

    async def mark_ready(
        self, *, project_id: str, story_id: str,
    ) -> DesignBrief | None:
        return await self._set_status(
            project_id, story_id, BriefStatus.READY,
        )

    async def approve(
        self, *, project_id: str, story_id: str, note: str = "",
    ) -> DesignBrief | None:
        return await self._set_status(
            project_id, story_id, BriefStatus.APPROVED, note=note,
        )

    async def request_changes(
        self, *, project_id: str, story_id: str, note: str = "",
    ) -> DesignBrief | None:
        return await self._set_status(
            project_id, story_id, BriefStatus.CHANGES_REQUESTED, note=note,
        )

    async def _set_status(
        self,
        project_id: str,
        story_id: str,
        status: BriefStatus,
        *,
        note: str = "",
    ) -> DesignBrief | None:
        existing = await self._repo.get_for_story(project_id, story_id)
        if existing is None:
            return None
        updated = replace(
            existing,
            status=status,
            approval_note=note or existing.approval_note,
            updated_at=_now(),
        )
        return await self._repo.upsert(updated)

    async def get(
        self, project_id: str, story_id: str,
    ) -> DesignBrief | None:
        return await self._repo.get_for_story(project_id, story_id)

    async def list(self, project_id: str) -> list[DesignBrief]:
        return await self._repo.list_for_project(project_id)


class VisualRegressionService:
    """Designer/QA co-review of visual regression diffs."""

    def __init__(self, repo: SQLiteVisualRegressionRepository) -> None:
        self._repo = repo

    async def capture(
        self,
        *,
        project_id: str,
        story_id: str = "",
        viewport: str = "",
        before_path: str = "",
        after_path: str = "",
        mask_notes: str = "",
    ) -> VisualRegression:
        entry = VisualRegression(
            id=VisualRegression.new_id(),
            project_id=project_id,
            story_id=story_id,
            viewport=viewport,
            before_path=before_path,
            after_path=after_path,
            mask_notes=mask_notes,
            status=CheckStatus.UNKNOWN,
        )
        return await self._repo.add(entry)

    async def review(
        self,
        *,
        entry_id: str,
        status: CheckStatus,
        note: str = "",
    ) -> VisualRegression | None:
        await self._repo.review(
            entry_id, status=status, reviewer_note=note,
        )
        return await self._repo.get(entry_id)

    async def list_for_story(
        self, project_id: str, story_id: str,
    ) -> list[VisualRegression]:
        return await self._repo.list_for_story(project_id, story_id)

    async def list_for_project(
        self, project_id: str, *, limit: int = 50,
    ) -> list[VisualRegression]:
        return await self._repo.list_for_project(project_id, limit=limit)


class AntiTemplateService:
    """Ship-bar against web/design-quality rules for UI PRs."""

    def __init__(self, repo: SQLiteAntiTemplateRepository) -> None:
        self._repo = repo

    async def record(
        self,
        *,
        project_id: str,
        story_id: str = "",
        pr_url: str = "",
        qualities: tuple[str, ...] = (),
        violations: tuple[str, ...] = (),
        summary: str = "",
    ) -> AntiTemplateCheck:
        # Auto-derive status from qualities + violations count.
        if len(violations) > 0:
            status = CheckStatus.FAIL
        elif len(qualities) >= AntiTemplateCheck.REQUIRED_QUALITIES:
            status = CheckStatus.PASS
        else:
            status = CheckStatus.WARN
        entry = AntiTemplateCheck(
            id=AntiTemplateCheck.new_id(),
            project_id=project_id,
            story_id=story_id,
            pr_url=pr_url,
            status=status,
            qualities=qualities,
            violations=violations,
            summary=summary,
        )
        return await self._repo.add(entry)

    async def latest_for_story(
        self, project_id: str, story_id: str,
    ) -> AntiTemplateCheck | None:
        return await self._repo.latest_for_story(project_id, story_id)

    async def list(
        self, project_id: str, *, limit: int = 30,
    ) -> list[AntiTemplateCheck]:
        return await self._repo.list_for_project(project_id, limit=limit)
