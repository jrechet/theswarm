"""Value objects for the Writer bounded context (Phase J)."""

from __future__ import annotations

from enum import Enum


class DocKind(str, Enum):
    """Type of documentation artifact."""

    README = "readme"
    QUICKSTART = "quickstart"
    CHANGELOG = "changelog"
    GUIDE = "guide"
    API = "api"


class DocStatus(str, Enum):
    """Where the doc stands."""

    DRAFT = "draft"
    READY = "ready"
    STALE = "stale"  # code changed; doc needs refresh


class QuickstartOutcome(str, Enum):
    """Result of running the documented quickstart."""

    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


class ChangeKind(str, Enum):
    """Conventional-commits aligned change types."""

    FEAT = "feat"
    FIX = "fix"
    REFACTOR = "refactor"
    PERF = "perf"
    DOCS = "docs"
    CHORE = "chore"
    BREAKING = "breaking"
