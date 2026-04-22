"""Product-intelligence entities.

All entities are frozen dataclasses. Mutation is done via ``dataclasses.replace``.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.product.value_objects import (
    InsightKind,
    ProposalStatus,
    SignalKind,
    SignalSeverity,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Proposal ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Proposal:
    """A candidate story the PO considers running into backlog.

    Proposals are created by the PO (from competitor moves, ecosystem trends,
    customer signals) and await human triage in the dashboard inbox.
    """

    id: str
    project_id: str
    title: str
    summary: str = ""
    rationale: str = ""          # "Why now" paragraph
    source_url: str = ""
    evidence_excerpt: str = ""
    confidence: float = 0.5      # 0.0-1.0
    status: ProposalStatus = ProposalStatus.PROPOSED
    codename: str = ""           # which PO proposed it
    tags: tuple[str, ...] = ()
    metadata: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    decided_at: datetime | None = None
    decision_note: str = ""
    linked_story_id: str = ""    # filled when approved → story

    @staticmethod
    def new_id() -> str:
        return f"prop_{uuid.uuid4().hex[:12]}"

    @staticmethod
    def dedup_key(project_id: str, title: str) -> str:
        """Stable hash for de-duplication across runs."""
        seed = f"{project_id}::{title.lower().strip()}".encode()
        return hashlib.sha256(seed).hexdigest()[:16]


# ── OKR ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class KeyResult:
    """One Key Result under an Objective."""

    id: str
    description: str
    target: str = ""          # e.g., "sign-up conversion >= 5%"
    baseline: str = ""
    current: str = ""
    progress: float = 0.0     # 0.0-1.0

    @staticmethod
    def new_id() -> str:
        return f"kr_{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class OKR:
    """Project OKR (Objective + Key Results) for outcome framing."""

    id: str
    project_id: str
    objective: str
    key_results: tuple[KeyResult, ...] = ()
    quarter: str = ""         # e.g., "2026-Q2"
    owner_codename: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    active: bool = True

    @staticmethod
    def new_id() -> str:
        return f"okr_{uuid.uuid4().hex[:12]}"


# ── Policy ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Policy:
    """Hard product rules for a project.

    Used as a filter on generated stories / proposals. If a story trips one of
    the banned terms or scopes, the PO must flag for human confirmation.
    """

    id: str
    project_id: str
    title: str = "Project policy"
    body_markdown: str = ""        # human-authored rules
    banned_terms: tuple[str, ...] = ()
    require_review_terms: tuple[str, ...] = ()
    updated_at: datetime = field(default_factory=_now)
    updated_by: str = ""           # codename or "human"

    @staticmethod
    def new_id() -> str:
        return f"pol_{uuid.uuid4().hex[:12]}"


# ── Signal ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Signal:
    """Observed market / customer / competitor event."""

    id: str
    project_id: str
    kind: SignalKind
    severity: SignalSeverity
    title: str
    body: str = ""
    source_url: str = ""
    source_name: str = ""
    tags: tuple[str, ...] = ()
    observed_at: datetime = field(default_factory=_now)
    metadata: dict = field(default_factory=dict)

    @staticmethod
    def new_id() -> str:
        return f"sig_{uuid.uuid4().hex[:12]}"


# ── Digest ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DigestItem:
    """A single line in an insight digest."""

    kind: InsightKind
    headline: str
    body: str = ""
    source_url: str = ""


@dataclass(frozen=True)
class InsightDigest:
    """Weekly summary of insights for a project (or portfolio)."""

    id: str
    project_id: str           # empty = portfolio-wide
    week_start: datetime
    items: tuple[DigestItem, ...] = ()
    narrative: str = ""       # prose summary on top
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return f"dig_{uuid.uuid4().hex[:12]}"
