"""Entities for the Scout bounded context (Phase G)."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.scout.value_objects import (
    IntelCategory,
    IntelUrgency,
    SourceKind,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rand(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def hash_url(url: str) -> str:
    """Stable URL hash for deduplication (strip scheme + trailing slash)."""
    normalized = url.strip().lower()
    for prefix in ("https://", "http://"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break
    normalized = normalized.rstrip("/")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:32]


@dataclass(frozen=True)
class IntelSource:
    """Upstream feed/source. Health tracked via success/error counters."""

    id: str
    name: str  # human-readable (e.g. "HackerNews top")
    kind: SourceKind = SourceKind.CUSTOM
    url: str = ""
    project_id: str = ""  # empty → portfolio-wide
    enabled: bool = True
    success_count: int = 0
    error_count: int = 0
    last_ok_at: datetime | None = None
    last_error: str = ""
    last_error_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("src")

    @property
    def total_attempts(self) -> int:
        return self.success_count + self.error_count

    @property
    def signal_rate(self) -> float:
        """Fraction of attempts that succeeded, in [0, 1]."""
        total = self.total_attempts
        if total <= 0:
            return 0.0
        return round(self.success_count / total, 3)

    @property
    def is_healthy(self) -> bool:
        """True if no errors or >= 80% signal rate with at least one success."""
        if self.success_count == 0 and self.error_count == 0:
            return True  # never checked, assume fine
        return self.signal_rate >= 0.8


@dataclass(frozen=True)
class IntelItem:
    """Single classified item from a source."""

    id: str
    source_id: str = ""
    title: str = ""
    url: str = ""
    url_hash: str = ""  # derived from url; used for dedup
    summary: str = ""
    category: IntelCategory = IntelCategory.FYI
    urgency: IntelUrgency = IntelUrgency.NORMAL
    project_ids: tuple[str, ...] = ()  # affected projects (empty → portfolio)
    cluster_id: str = ""  # optional grouping
    action_taken: str = ""  # free text (e.g. "opened issue #42")
    action_taken_at: datetime | None = None
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("intel")

    @property
    def is_actionable(self) -> bool:
        """True for categories where a human almost always decides something."""
        return self.category in {
            IntelCategory.THREAT,
            IntelCategory.CVE,
            IntelCategory.OPPORTUNITY,
        }

    @property
    def has_action(self) -> bool:
        return bool(self.action_taken)


@dataclass(frozen=True)
class IntelCluster:
    """Group of related intel items (same story across sources)."""

    id: str
    topic: str = ""  # short human label (e.g. "Python 3.13 release")
    summary: str = ""
    member_ids: tuple[str, ...] = ()
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("cluster")

    @property
    def size(self) -> int:
        return len(self.member_ids)
