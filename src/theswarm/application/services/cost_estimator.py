"""Sprint D C5 — estimate tokens + USD for the next cycle."""

from __future__ import annotations

from dataclasses import dataclass

from theswarm.application.services.effort_profile import EffortProfile
from theswarm.domain.cycles.value_objects import CycleStatus
from theswarm.domain.projects.entities import Project

_MODEL_BASELINE_TOKENS: dict[str, int] = {
    "haiku": 40_000,
    "sonnet": 120_000,
    "opus": 200_000,
}

_MODEL_PRICE_PER_1K: dict[str, float] = {
    "haiku": 0.0025,
    "sonnet": 0.015,
    "opus": 0.075,
}


@dataclass(frozen=True)
class CostEstimate:
    tokens: int
    cost_usd: float
    basis: str
    sample_size: int
    models_by_phase: dict[str, str]


class CostEstimator:
    """Estimate expected tokens/cost for a project's next cycle."""

    def __init__(self, cycle_repo: object | None) -> None:
        self._cycle_repo = cycle_repo

    async def estimate(self, project: Project) -> CostEstimate:
        resolved = EffortProfile.apply(project.config)
        models_by_phase = dict(resolved.models)

        completed = await self._recent_completed(project.id, limit=3)
        if completed:
            avg_tokens = sum(c.total_tokens for c in completed) // len(completed)
            avg_cost = sum(c.total_cost_usd for c in completed) / len(completed)
            return CostEstimate(
                tokens=max(0, avg_tokens),
                cost_usd=round(max(0.0, avg_cost), 4),
                basis="history",
                sample_size=len(completed),
                models_by_phase=models_by_phase,
            )

        total_tokens = sum(
            _MODEL_BASELINE_TOKENS.get(model, 80_000)
            for model in models_by_phase.values()
        )
        total_cost = sum(
            (_MODEL_BASELINE_TOKENS.get(model, 80_000) / 1000.0)
            * _MODEL_PRICE_PER_1K.get(model, 0.01)
            for model in models_by_phase.values()
        )
        return CostEstimate(
            tokens=total_tokens,
            cost_usd=round(total_cost, 4),
            basis="model_baseline",
            sample_size=0,
            models_by_phase=models_by_phase,
        )

    async def _recent_completed(self, project_id: str, limit: int) -> list:
        if self._cycle_repo is None:
            return []
        cycles = await self._cycle_repo.list_by_project(project_id, limit=limit * 3)
        completed = [c for c in cycles if c.status == CycleStatus.COMPLETED]
        return completed[:limit]
