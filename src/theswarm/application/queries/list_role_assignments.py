"""Queries exposing the role/codename roster for dashboards."""

from __future__ import annotations

from dataclasses import dataclass

from theswarm.domain.agents.entities import PORTFOLIO_PROJECT_ID
from theswarm.domain.agents.ports import RoleAssignmentRepository


@dataclass(frozen=True)
class RosterEntry:
    """Flat DTO for a single role assignment row in the UI."""

    project_id: str
    role: str
    codename: str
    is_portfolio: bool
    assigned_at: str


class ListRoleAssignmentsQuery:
    """List role assignments for a project + portfolio overlay."""

    def __init__(self, repo: RoleAssignmentRepository) -> None:
        self._repo = repo

    async def for_project(self, project_id: str) -> list[RosterEntry]:
        """Return the project's own roster followed by portfolio roles.

        Portfolio roles are appended so every project page shows the full
        effective team even if those roles live under the portfolio scope.
        """
        out: list[RosterEntry] = []
        seen: set[tuple[str, str]] = set()

        project_roster = await self._repo.list_for_project(
            project_id, include_retired=False,
        )
        for a in project_roster:
            key = (a.project_id, a.role.value)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                RosterEntry(
                    project_id=a.project_id,
                    role=a.role.value,
                    codename=a.codename,
                    is_portfolio=a.is_portfolio,
                    assigned_at=a.assigned_at.isoformat(),
                ),
            )

        portfolio_roster = await self._repo.list_for_project(
            PORTFOLIO_PROJECT_ID, include_retired=False,
        )
        for a in portfolio_roster:
            key = (a.project_id, a.role.value)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                RosterEntry(
                    project_id=a.project_id,
                    role=a.role.value,
                    codename=a.codename,
                    is_portfolio=True,
                    assigned_at=a.assigned_at.isoformat(),
                ),
            )
        return out

    async def all(self) -> list[RosterEntry]:
        """Return every active assignment for the global roster page."""
        assignments = await self._repo.list_all(include_retired=False)
        return [
            RosterEntry(
                project_id=a.project_id,
                role=a.role.value,
                codename=a.codename,
                is_portfolio=a.is_portfolio,
                assigned_at=a.assigned_at.isoformat(),
            )
            for a in assignments
        ]
