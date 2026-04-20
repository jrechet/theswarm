"""Command: PATCH a project's configuration fields."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from theswarm.domain.projects.entities import ProjectConfig
from theswarm.domain.projects.ports import ProjectRepository

_VALID_PHASES = {"po", "techlead", "dev", "qa"}


class ProjectNotFound(ValueError):
    pass


@dataclass(frozen=True)
class UpdateProjectConfigCommand:
    """Partial update: any field left as None keeps its current value."""

    project_id: str
    effort: str | None = None
    models: dict[str, str] | None = None
    max_daily_stories: int | None = None
    daily_cost_cap_usd: float | None = None
    daily_tokens_cap: int | None = None
    monthly_cost_cap_usd: float | None = None
    paused: bool | None = None
    token_budget_po: int | None = None
    token_budget_techlead: int | None = None
    token_budget_dev: int | None = None
    token_budget_qa: int | None = None
    preview_url_template: str | None = None


class UpdateProjectConfigHandler:
    def __init__(self, project_repo: ProjectRepository) -> None:
        self._project_repo = project_repo

    async def handle(self, cmd: UpdateProjectConfigCommand) -> ProjectConfig:
        project = await self._project_repo.get(cmd.project_id)
        if project is None:
            raise ProjectNotFound(f"project not found: {cmd.project_id}")

        changes: dict = {}
        if cmd.effort is not None:
            changes["effort"] = cmd.effort
        if cmd.models is not None:
            unknown = set(cmd.models) - _VALID_PHASES
            if unknown:
                raise ValueError(f"unknown model phases: {sorted(unknown)}")
            merged = dict(project.config.models)
            for k, v in cmd.models.items():
                if not isinstance(v, str) or not v:
                    raise ValueError(f"model for {k!r} must be a non-empty string")
                merged[k] = v
            changes["models"] = merged
        if cmd.max_daily_stories is not None:
            if cmd.max_daily_stories < 0:
                raise ValueError("max_daily_stories must be >= 0")
            changes["max_daily_stories"] = cmd.max_daily_stories
        if cmd.daily_cost_cap_usd is not None:
            changes["daily_cost_cap_usd"] = float(cmd.daily_cost_cap_usd)
        if cmd.daily_tokens_cap is not None:
            changes["daily_tokens_cap"] = int(cmd.daily_tokens_cap)
        if cmd.monthly_cost_cap_usd is not None:
            changes["monthly_cost_cap_usd"] = float(cmd.monthly_cost_cap_usd)
        if cmd.paused is not None:
            changes["paused"] = bool(cmd.paused)
        if cmd.token_budget_po is not None:
            changes["token_budget_po"] = int(cmd.token_budget_po)
        if cmd.token_budget_techlead is not None:
            changes["token_budget_techlead"] = int(cmd.token_budget_techlead)
        if cmd.token_budget_dev is not None:
            changes["token_budget_dev"] = int(cmd.token_budget_dev)
        if cmd.token_budget_qa is not None:
            changes["token_budget_qa"] = int(cmd.token_budget_qa)
        if cmd.preview_url_template is not None:
            changes["preview_url_template"] = str(cmd.preview_url_template)

        new_config = replace(project.config, **changes)
        await self._project_repo.save(project.with_config(new_config))
        return new_config
