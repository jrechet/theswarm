"""Entities for the Designer bounded context (Phase H)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.designer.value_objects import (
    BriefStatus,
    CheckStatus,
    ComponentStatus,
    TokenKind,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rand(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


@dataclass(frozen=True)
class DesignToken:
    """A single entry in the design system (e.g. --color-accent)."""

    id: str
    project_id: str
    name: str
    kind: TokenKind = TokenKind.OTHER
    value: str = ""  # raw css value or hex
    notes: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("tok")


@dataclass(frozen=True)
class ComponentEntry:
    """Inventory entry for a UI component (promotable / deprecatable)."""

    id: str
    project_id: str
    name: str
    status: ComponentStatus = ComponentStatus.PROPOSED
    path: str = ""  # e.g. src/components/Button.tsx
    usage_count: int = 0
    notes: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("comp")

    @property
    def is_shared(self) -> bool:
        return self.status == ComponentStatus.SHARED

    @property
    def is_retired(self) -> bool:
        return self.status in {
            ComponentStatus.DEPRECATED,
            ComponentStatus.LEGACY,
        }


@dataclass(frozen=True)
class DesignBrief:
    """Lightweight design brief for a UI story — gates Dev work."""

    id: str
    project_id: str
    story_id: str = ""
    title: str = ""
    intent: str = ""  # what the UI change is trying to achieve
    hierarchy: str = ""  # information hierarchy / primary surface
    states: str = ""  # key states: empty/loading/error/active/etc.
    motion: str = ""  # motion intent + compositor-friendly props
    reference_url: str = ""  # figma link / mood image / competitor ref
    status: BriefStatus = BriefStatus.DRAFT
    approval_note: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("brief")

    @property
    def is_approved(self) -> bool:
        return self.status == BriefStatus.APPROVED

    @property
    def blocks_dev(self) -> bool:
        """Dev must wait until the brief is at least READY or APPROVED."""
        return self.status in {
            BriefStatus.DRAFT,
            BriefStatus.CHANGES_REQUESTED,
        }


@dataclass(frozen=True)
class VisualRegression:
    """Designer/QA co-review record for a visual regression check."""

    id: str
    project_id: str
    story_id: str = ""
    viewport: str = ""  # e.g. "1440x900"
    before_path: str = ""
    after_path: str = ""
    mask_notes: str = ""  # what areas were masked for the diff
    status: CheckStatus = CheckStatus.UNKNOWN
    reviewer_note: str = ""
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("vr")

    @property
    def is_blocking(self) -> bool:
        return self.status == CheckStatus.FAIL


@dataclass(frozen=True)
class AntiTemplateCheck:
    """Ship-bar result for a UI change against design-quality rules."""

    id: str
    project_id: str
    story_id: str = ""
    pr_url: str = ""
    status: CheckStatus = CheckStatus.UNKNOWN
    violations: tuple[str, ...] = ()  # short rule names
    qualities: tuple[str, ...] = ()  # required qualities demonstrated
    summary: str = ""
    created_at: datetime = field(default_factory=_now)

    # Phase H threshold: required qualities >= 4 AND no violations.
    REQUIRED_QUALITIES = 4

    @staticmethod
    def new_id() -> str:
        return _rand("atc")

    @property
    def quality_count(self) -> int:
        return len(self.qualities)

    @property
    def passes_bar(self) -> bool:
        return (
            self.quality_count >= self.REQUIRED_QUALITIES
            and len(self.violations) == 0
        )
