"""Sprint B C2 — map project effort level to concrete agent settings.

Maps `ProjectConfig.effort` to a resolved bundle of model choices, retry
budgets, and thinking budget. Explicit overrides in `ProjectConfig.models`
always win over the preset.
"""

from __future__ import annotations

from dataclasses import dataclass

from theswarm.domain.projects.entities import ProjectConfig

_PHASES = ("po", "techlead", "dev", "qa")


@dataclass(frozen=True)
class ResolvedEffort:
    """Concrete values resolved from a project's effort level + overrides."""

    models: dict[str, str]
    max_retries: int
    thinking_budget: int


_PRESETS: dict[str, ResolvedEffort] = {
    "low": ResolvedEffort(
        models={"po": "haiku", "techlead": "haiku", "dev": "haiku", "qa": "haiku"},
        max_retries=1,
        thinking_budget=0,
    ),
    "medium": ResolvedEffort(
        models={"po": "sonnet", "techlead": "sonnet", "dev": "sonnet", "qa": "haiku"},
        max_retries=2,
        thinking_budget=2000,
    ),
    "high": ResolvedEffort(
        models={"po": "opus", "techlead": "opus", "dev": "opus", "qa": "sonnet"},
        max_retries=5,
        thinking_budget=10_000,
    ),
}


class EffortProfile:
    """Resolve a project's effort level to concrete agent settings."""

    @staticmethod
    def apply(config: ProjectConfig) -> ResolvedEffort:
        preset = _PRESETS.get(config.effort)
        if preset is None:
            raise ValueError(f"unknown effort level: {config.effort!r}")

        # Explicit per-phase overrides in config.models win over the preset
        merged = dict(preset.models)
        for phase, model in config.models.items():
            if phase in _PHASES and model:
                merged[phase] = model

        return ResolvedEffort(
            models=merged,
            max_retries=preset.max_retries,
            thinking_budget=preset.thinking_budget,
        )
