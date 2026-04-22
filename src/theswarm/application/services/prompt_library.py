"""Application service for prompt library (Phase L)."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone

from theswarm.domain.prompt_library.entities import (
    PromptAuditEntry,
    PromptTemplate,
)
from theswarm.domain.prompt_library.value_objects import PromptAuditAction


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class PromptLibraryService:
    def __init__(self, template_repo, audit_repo) -> None:
        self._templates = template_repo
        self._audits = audit_repo

    async def upsert(
        self, name: str, body: str = "", role: str = "",
        actor: str = "", note: str = "",
    ) -> PromptTemplate:
        existing = await self._templates.get_by_name(name)
        now = _now()
        if existing is None:
            t = PromptTemplate(
                id=_uid(), name=name, role=role, body=body,
                version=1, deprecated=False, updated_by=actor,
                created_at=now, updated_at=now,
            )
            saved = await self._templates.upsert(t)
            # Guard against concurrent CREATE racing to the same name: the
            # template repo dedupes via ON CONFLICT, so only emit the CREATE
            # audit row when no audit history exists yet.
            prior_audits = await self._audits.list_for_prompt(name)
            if not prior_audits:
                await self._audits.add(PromptAuditEntry(
                    id=_uid(), prompt_name=name,
                    action=PromptAuditAction.CREATE,
                    actor=actor, before_version=0,
                    after_version=saved.version,
                    note=note, created_at=now,
                ))
            return saved
        # Noop when neither body nor role changed — don't touch the template
        # and don't write an audit entry (keeps the audit trail meaningful and
        # matches deprecate/restore idempotency semantics).
        if existing.body == body and existing.role == role:
            return existing
        before_version = existing.version
        new_version = before_version + 1
        t = replace(
            existing, role=role, body=body, version=new_version,
            updated_by=actor, updated_at=now,
        )
        saved = await self._templates.upsert(t)
        await self._audits.add(PromptAuditEntry(
            id=_uid(), prompt_name=name,
            action=PromptAuditAction.UPDATE,
            actor=actor, before_version=before_version,
            after_version=new_version, note=note, created_at=now,
        ))
        return saved

    async def deprecate(
        self, name: str, actor: str = "", note: str = "",
    ) -> PromptTemplate:
        existing = await self._templates.get_by_name(name)
        if existing is None:
            raise ValueError(f"Prompt not found: {name}")
        if existing.deprecated:
            return existing
        now = _now()
        t = replace(
            existing, deprecated=True, updated_by=actor, updated_at=now,
        )
        saved = await self._templates.upsert(t)
        await self._audits.add(PromptAuditEntry(
            id=_uid(), prompt_name=name,
            action=PromptAuditAction.DEPRECATE,
            actor=actor, before_version=existing.version,
            after_version=existing.version, note=note, created_at=now,
        ))
        return saved

    async def restore(
        self, name: str, actor: str = "", note: str = "",
    ) -> PromptTemplate:
        existing = await self._templates.get_by_name(name)
        if existing is None:
            raise ValueError(f"Prompt not found: {name}")
        if not existing.deprecated:
            return existing
        now = _now()
        t = replace(
            existing, deprecated=False, updated_by=actor, updated_at=now,
        )
        saved = await self._templates.upsert(t)
        await self._audits.add(PromptAuditEntry(
            id=_uid(), prompt_name=name,
            action=PromptAuditAction.RESTORE,
            actor=actor, before_version=existing.version,
            after_version=existing.version, note=note, created_at=now,
        ))
        return saved

    async def list(self) -> list[PromptTemplate]:
        return await self._templates.list_all()

    async def get(self, name: str) -> PromptTemplate | None:
        return await self._templates.get_by_name(name)

    async def list_audit(
        self, name: str | None = None,
    ) -> list[PromptAuditEntry]:
        if name is None:
            return await self._audits.list_all()
        return await self._audits.list_for_prompt(name)
