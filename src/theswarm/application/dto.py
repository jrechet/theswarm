"""Data Transfer Objects for the application layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class ProjectDTO:
    """Project data for presentation layer."""

    id: str
    repo: str
    default_branch: str
    framework: str
    ticket_source: str
    team_channel: str
    schedule: str
    test_command: str
    source_dir: str
    max_daily_stories: int
    created_at: str
    # Sprint B controls
    effort: str = "medium"
    models: dict = field(default_factory=dict)
    daily_cost_cap_usd: float = 0.0
    daily_tokens_cap: int = 0
    monthly_cost_cap_usd: float = 0.0
    paused: bool = False


@dataclass(frozen=True)
class CycleDTO:
    """Cycle data for presentation layer."""

    id: str
    project_id: str
    status: str
    triggered_by: str
    started_at: str | None
    completed_at: str | None
    total_tokens: int
    total_cost_usd: float
    prs_opened: list[int]
    prs_merged: list[int]
    phases: list[PhaseDTO]

    @property
    def duration_seconds(self) -> int | None:
        """Compute duration in seconds from started_at to completed_at (or now)."""
        if not self.started_at:
            return None
        try:
            start = datetime.fromisoformat(self.started_at)
            if self.completed_at:
                end = datetime.fromisoformat(self.completed_at)
            else:
                end = datetime.now(timezone.utc)
            return max(0, int((end - start).total_seconds()))
        except (ValueError, TypeError):
            return None

    @property
    def duration_display(self) -> str:
        """Human-readable duration (e.g. '23m 45s', '1h 12m')."""
        secs = self.duration_seconds
        if secs is None:
            return "---"
        if secs < 60:
            return f"{secs}s"
        minutes = secs // 60
        remaining_secs = secs % 60
        if minutes < 60:
            return f"{minutes}m {remaining_secs}s"
        hours = minutes // 60
        remaining_mins = minutes % 60
        return f"{hours}h {remaining_mins}m"

    @property
    def current_phase_name(self) -> str:
        """Name of the currently running phase, or last phase."""
        if not self.phases:
            return ""
        for p in reversed(self.phases):
            if p.status == "running":
                return f"{p.agent}: {p.phase}"
        return self.phases[-1].phase

    @property
    def progress_percent(self) -> int:
        """Estimated progress (0-100) based on known phase sequence."""
        if not self.phases:
            return 0
        # Known phase count: PO morning, TL breakdown, Dev(x5), TL review(x5), QA, PO evening ~14
        total_expected = 8
        completed = sum(1 for p in self.phases if p.status in ("completed", "failed"))
        return min(100, int(completed / total_expected * 100))


@dataclass(frozen=True)
class PhaseDTO:
    """Phase execution data for presentation layer."""

    phase: str
    agent: str
    status: str
    started_at: str
    completed_at: str | None
    tokens_used: int
    cost_usd: float
    summary: str

    @property
    def duration_seconds(self) -> float | None:
        if not self.started_at:
            return None
        try:
            start = datetime.fromisoformat(self.started_at)
            end = (
                datetime.fromisoformat(self.completed_at)
                if self.completed_at
                else datetime.now(timezone.utc)
            )
            return max(0.0, (end - start).total_seconds())
        except (ValueError, TypeError):
            return None

    @property
    def start_time_display(self) -> str:
        try:
            return datetime.fromisoformat(self.started_at).strftime("%H:%M:%S")
        except (ValueError, TypeError):
            return ""


@dataclass(frozen=True)
class ActivityDTO:
    """Agent activity data for live feeds."""

    timestamp: str
    project_id: str
    agent: str
    action: str
    detail: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ReportDTO:
    """Demo report data for presentation layer."""

    id: str
    cycle_id: str
    project_id: str
    created_at: str
    stories_completed: int
    stories_total: int
    prs_merged: int
    tests_passing: int
    coverage_percent: float
    cost_usd: float
    screenshot_count: int
    video_count: int


@dataclass(frozen=True)
class DashboardDTO:
    """Dashboard state for presentation layer."""

    active_cycles: list[CycleDTO]
    recent_cycles: list[CycleDTO]
    recent_activities: list[ActivityDTO]
    projects: list[ProjectDTO]
    total_cost_today: float = 0.0
    total_cost_week: float = 0.0
    success_rate_7d: float = 0.0
    cycles_completed_7d: int = 0
    cycles_failed_7d: int = 0
    cost_per_day_7d: tuple[float, ...] = ()  # oldest→newest, 7 entries
    cycles_per_day_7d: tuple[int, ...] = ()
