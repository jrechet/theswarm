"""Value objects for the Reporting bounded context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class ArtifactType(str, Enum):
    SCREENSHOT = "screenshot"
    VIDEO = "video"
    DIFF = "diff"
    LOG = "log"


class QualityStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIP = "skip"


@dataclass(frozen=True)
class Artifact:
    """A captured artifact: screenshot, video, diff, or log."""

    type: ArtifactType
    label: str
    path: str
    mime_type: str = ""
    size_bytes: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class DiffHighlight:
    """An annotated code change."""

    file_path: str
    hunk: str
    annotation: str = ""
    lines_added: int = 0
    lines_removed: int = 0


@dataclass(frozen=True)
class QualityGate:
    """Result of a quality check."""

    name: str
    status: QualityStatus
    detail: str = ""
    value: float | None = None  # e.g. coverage %
