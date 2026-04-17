"""Query: assemble dashboard state from multiple sources."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from theswarm.application.dto import (
    ActivityDTO,
    CycleDTO,
    DashboardDTO,
    PhaseDTO,
    ProjectDTO,
)
from theswarm.domain.cycles.ports import CycleRepository
from theswarm.domain.cycles.value_objects import CycleStatus
from theswarm.domain.projects.ports import ProjectRepository


class GetDashboardQuery:
    def __init__(
        self,
        project_repo: ProjectRepository,
        cycle_repo: CycleRepository,
        activity_repo: object | None = None,
    ) -> None:
        self._project_repo = project_repo
        self._cycle_repo = cycle_repo
        self._activity_repo = activity_repo

    async def execute(self) -> DashboardDTO:
        projects = await self._project_repo.list_all()

        project_dtos = [
            ProjectDTO(
                id=p.id,
                repo=str(p.repo),
                default_branch=p.default_branch,
                framework=p.framework.value,
                ticket_source=p.ticket_source.value,
                team_channel=p.team_channel,
                schedule=p.schedule,
                test_command=p.test_command,
                source_dir=p.source_dir,
                max_daily_stories=p.config.max_daily_stories,
                created_at=p.created_at.isoformat(),
            )
            for p in projects
        ]

        # Get all recent cycles across projects
        all_cycles = await self._cycle_repo.list_recent(limit=50)

        active_cycles: list[CycleDTO] = []
        recent_cycles: list[CycleDTO] = []
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_ago = now - timedelta(days=7)

        total_cost_today = 0.0
        total_cost_week = 0.0
        completed_7d = 0
        failed_7d = 0
        cost_bins = [0.0] * 7  # index 0 = 6 days ago, index 6 = today
        cycle_bins = [0] * 7
        today_date = today_start.date()

        for c in all_cycles:
            dto = CycleDTO(
                id=str(c.id),
                project_id=c.project_id,
                status=c.status.value,
                triggered_by=c.triggered_by,
                started_at=c.started_at.isoformat() if c.started_at else None,
                completed_at=c.completed_at.isoformat() if c.completed_at else None,
                total_tokens=c.total_tokens,
                total_cost_usd=c.total_cost_usd,
                prs_opened=list(c.prs_opened),
                prs_merged=list(c.prs_merged),
                phases=[
                    PhaseDTO(
                        phase=p.phase,
                        agent=p.agent,
                        status=p.status.value,
                        started_at=p.started_at.isoformat(),
                        completed_at=p.completed_at.isoformat() if p.completed_at else None,
                        tokens_used=p.tokens_used,
                        cost_usd=p.cost_usd,
                        summary=p.summary,
                    )
                    for p in c.phases
                ],
            )

            if c.status == CycleStatus.RUNNING:
                active_cycles.append(dto)
            elif len(recent_cycles) < 10:
                recent_cycles.append(dto)

            # Cost calculations
            started = c.started_at
            if started:
                if started >= today_start:
                    total_cost_today += c.total_cost_usd
                if started >= week_ago:
                    total_cost_week += c.total_cost_usd
                    if c.status == CycleStatus.COMPLETED:
                        completed_7d += 1
                    elif c.status == CycleStatus.FAILED:
                        failed_7d += 1
                    # Bucket into the right day slot
                    days_ago = (today_date - started.date()).days
                    if 0 <= days_ago < 7:
                        idx = 6 - days_ago
                        cost_bins[idx] += c.total_cost_usd
                        cycle_bins[idx] += 1

        total_7d = completed_7d + failed_7d
        success_rate = (completed_7d / total_7d * 100) if total_7d > 0 else 0.0

        # Recent activities
        activities: list[ActivityDTO] = []
        if self._activity_repo is not None and hasattr(self._activity_repo, "list_recent"):
            raw = await self._activity_repo.list_recent(limit=20)
            activities = [
                ActivityDTO(
                    timestamp=a["created_at"],
                    project_id=a["project_id"],
                    agent=a["agent"],
                    action=a["action"],
                    detail=a["detail"],
                    metadata=a.get("metadata", {}),
                )
                for a in raw
            ]

        return DashboardDTO(
            active_cycles=active_cycles,
            recent_cycles=recent_cycles,
            recent_activities=activities,
            projects=project_dtos,
            total_cost_today=total_cost_today,
            total_cost_week=total_cost_week,
            success_rate_7d=success_rate,
            cycles_completed_7d=completed_7d,
            cycles_failed_7d=failed_7d,
            cost_per_day_7d=tuple(cost_bins),
            cycles_per_day_7d=tuple(cycle_bins),
        )
