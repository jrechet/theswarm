"""Entities for the Reporting bounded context."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.reporting.value_objects import (
    Artifact,
    DiffHighlight,
    QualityGate,
    QualityStatus,
)

PUBLIC_SLUG_LENGTH = 8


@dataclass(frozen=True)
class StoryReport:
    """Report for a single story within a cycle."""

    ticket_id: str
    title: str
    status: str  # "completed", "in_progress", "blocked"
    pr_number: int | None = None
    pr_url: str = ""
    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    screenshots_before: tuple[Artifact, ...] = ()
    screenshots_after: tuple[Artifact, ...] = ()
    video: Artifact | None = None
    diff_highlights: tuple[DiffHighlight, ...] = ()


@dataclass(frozen=True)
class ReportSummary:
    """High-level numbers for a demo report."""

    stories_completed: int = 0
    stories_total: int = 0
    prs_merged: int = 0
    tests_passing: int = 0
    tests_total: int = 0
    coverage_percent: float = 0.0
    security_critical: int = 0
    security_medium: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class DemoReport:
    """A full demo report for one cycle."""

    id: str
    cycle_id: CycleId
    project_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    summary: ReportSummary = field(default_factory=ReportSummary)
    stories: tuple[StoryReport, ...] = ()
    quality_gates: tuple[QualityGate, ...] = ()
    agent_learnings: tuple[str, ...] = ()
    artifacts: tuple[Artifact, ...] = ()

    @property
    def all_gates_pass(self) -> bool:
        return all(g.status != QualityStatus.FAIL for g in self.quality_gates)

    @property
    def public_slug(self) -> str:
        return hashlib.sha256(self.id.encode()).hexdigest()[:PUBLIC_SLUG_LENGTH]

    @property
    def screenshot_count(self) -> int:
        count = len([a for a in self.artifacts if a.type.value == "screenshot"])
        for s in self.stories:
            count += len(s.screenshots_before) + len(s.screenshots_after)
        return count

    @property
    def video_count(self) -> int:
        count = len([a for a in self.artifacts if a.type.value == "video"])
        for s in self.stories:
            if s.video:
                count += 1
        return count

    @property
    def thumbnail_path(self) -> str | None:
        """Relative artifact path of the first usable screenshot, or None."""
        for a in self.artifacts:
            if a.type.value == "screenshot" and a.path:
                return a.path
        for s in self.stories:
            for a in (*s.screenshots_after, *s.screenshots_before):
                if a.path:
                    return a.path
        return None
