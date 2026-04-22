"""Application service for assigning codenamed roles to projects.

Wraps the SQLite repository + codename picker, encapsulates "assign a core
roster at project creation", and is the single place that allocates codenames
so uniqueness is enforced consistently.
"""

from __future__ import annotations

import logging
from typing import Optional

from theswarm.domain.agents.entities import PORTFOLIO_PROJECT_ID, RoleAssignment
from theswarm.domain.agents.events import RoleAssigned
from theswarm.domain.agents.ports import RoleAssignmentRepository
from theswarm.domain.agents.value_objects import (
    CORE_PROJECT_ROLES,
    DEFAULT_ROLE_SCOPES,
    AgentRole,
    RoleScope,
)
from theswarm.infrastructure.agents.codename_pool import (
    CodenameExhausted,
    load_pool,
    pick_codename,
)

log = logging.getLogger(__name__)


class EventBusLike:
    """Minimal interface used from this service (avoids a hard import)."""

    async def publish(self, event) -> None: ...  # pragma: no cover


class RoleAssignmentService:
    """Assigns roles with auto-picked codenames and bus-publishes events."""

    def __init__(
        self,
        repo: RoleAssignmentRepository,
        event_bus: EventBusLike | None = None,
        pool: tuple[str, ...] | None = None,
    ) -> None:
        self._repo = repo
        self._bus = event_bus
        self._pool = pool if pool is not None else load_pool()

    @property
    def pool(self) -> tuple[str, ...]:
        return self._pool

    async def assign(
        self,
        project_id: str,
        role: AgentRole,
        codename: str | None = None,
        config: dict | None = None,
    ) -> RoleAssignment:
        """Create and persist a new role assignment. Idempotent if already active."""
        effective_project = self._effective_project_id(project_id, role)

        existing = await self._repo.find(effective_project, role)
        if existing is not None:
            return existing

        in_use = await self._repo.codenames_in_use()
        chosen = codename or pick_codename(
            project_id=effective_project,
            role=role.value,
            pool=self._pool,
            in_use=in_use,
        )
        if chosen in in_use:
            raise CodenameExhausted(
                f"Codename {chosen!r} is already in use; pick another.",
            )

        assignment = RoleAssignment(
            id=RoleAssignment.new_id(),
            project_id=effective_project,
            role=role,
            codename=chosen,
            config=config or {},
        )
        await self._repo.save(assignment)

        if self._bus is not None:
            try:
                await self._bus.publish(
                    RoleAssigned(
                        project_id=effective_project,
                        role=role.value,
                        codename=chosen,
                        assignment_id=assignment.id,
                    ),
                )
            except Exception:  # pragma: no cover — event-bus failure must not break assignment
                log.exception("Failed to publish RoleAssigned event")
        return assignment

    async def assign_core_roster(self, project_id: str) -> list[RoleAssignment]:
        """Assign the four core roles (PO/TechLead/Dev/QA) to a new project."""
        assignments: list[RoleAssignment] = []
        for role in CORE_PROJECT_ROLES:
            assignments.append(await self.assign(project_id, role))
        return assignments

    async def get_codename(
        self, project_id: str, role: AgentRole,
    ) -> Optional[str]:
        """Return the codename bound to (project, role), or None."""
        effective = self._effective_project_id(project_id, role)
        assignment = await self._repo.find(effective, role)
        return assignment.codename if assignment else None

    async def codename_map(self, project_id: str) -> dict[str, str]:
        """Return a ``{role_value: codename}`` map for project + portfolio roles.

        Agents consume this as ``state["codenames"]`` so prompts can reference
        the codename in first person. Portfolio-scoped roles are included so
        e.g. Scout/SRE/Security show up for every project.
        """
        mapping: dict[str, str] = {}
        project_assignments = await self._repo.list_for_project(
            project_id, include_retired=False,
        )
        for a in project_assignments:
            mapping[a.role.value] = a.codename
        portfolio_assignments = await self._repo.list_for_project(
            PORTFOLIO_PROJECT_ID, include_retired=False,
        )
        for a in portfolio_assignments:
            mapping.setdefault(a.role.value, a.codename)
        return mapping

    @staticmethod
    def _effective_project_id(project_id: str, role: AgentRole) -> str:
        """Portfolio-scoped roles ignore the caller's project_id."""
        scope = DEFAULT_ROLE_SCOPES.get(role, RoleScope.PROJECT)
        if scope is RoleScope.PORTFOLIO:
            return PORTFOLIO_PROJECT_ID
        return project_id
