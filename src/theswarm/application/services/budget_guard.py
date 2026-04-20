"""Sprint B C4 — enforce daily/monthly cost caps and pause switch.

Queries the cycle repository for spend in the current calendar day / month
(UTC) and blocks new cycles when a cap is hit. Also respects the pause flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from theswarm.domain.cycles.ports import CycleRepository
from theswarm.domain.projects.entities import Project


class CycleBlocked(RuntimeError):
    """Raised when a cycle cannot start because of a cap or pause."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Spend:
    daily_usd: float
    monthly_usd: float


class BudgetGuard:
    def __init__(
        self,
        cycle_repo: CycleRepository,
        *,
        now: "callable | None" = None,
    ) -> None:
        self._cycle_repo = cycle_repo
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def check(self, project: Project) -> None:
        """Raise `CycleBlocked` if the project is paused or has hit a cap."""
        if project.config.paused:
            raise CycleBlocked("paused")

        daily_cap = project.config.daily_cost_cap_usd
        monthly_cap = project.config.monthly_cost_cap_usd
        if daily_cap <= 0 and monthly_cap <= 0:
            return

        spend = await self._spend_for(project.id)

        if daily_cap > 0 and spend.daily_usd >= daily_cap:
            raise CycleBlocked(
                f"daily cap ${daily_cap:.2f} reached (spent ${spend.daily_usd:.2f})",
            )
        if monthly_cap > 0 and spend.monthly_usd >= monthly_cap:
            raise CycleBlocked(
                f"monthly cap ${monthly_cap:.2f} reached (spent ${spend.monthly_usd:.2f})",
            )

    async def _spend_for(self, project_id: str) -> Spend:
        now = self._now()
        today = now.date()
        month_start = now.replace(day=1).date()
        # Pull enough cycles to cover the window (UTC days); cap at 500
        cycles = await self._cycle_repo.list_by_project(project_id, limit=500)

        daily = 0.0
        monthly = 0.0
        for c in cycles:
            ref = c.started_at or c.completed_at
            if ref is None:
                continue
            ref_date = ref.astimezone(timezone.utc).date()
            if ref_date >= month_start:
                monthly += c.total_cost_usd
            if ref_date == today:
                daily += c.total_cost_usd
        return Spend(daily_usd=daily, monthly_usd=monthly)
