"""Data Transfer Objects for the application layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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
    recent_activities: list[ActivityDTO]
    projects: list[ProjectDTO]
    total_cost_today: float = 0.0
