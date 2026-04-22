"""SQLite implementation of the RoleAssignmentRepository port."""

from __future__ import annotations

import json
from datetime import datetime

import aiosqlite

from theswarm.domain.agents.entities import RoleAssignment
from theswarm.domain.agents.value_objects import AgentRole


class SQLiteRoleAssignmentRepository:
    """Persists role assignments in the ``role_assignments`` table."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def save(self, assignment: RoleAssignment) -> None:
        await self._db.execute(
            """INSERT OR REPLACE INTO role_assignments
               (id, project_id, role, codename, assigned_at, retired_at, config_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                assignment.id,
                assignment.project_id,
                assignment.role.value,
                assignment.codename,
                assignment.assigned_at.isoformat(),
                assignment.retired_at.isoformat() if assignment.retired_at else None,
                json.dumps(assignment.config or {}),
            ),
        )
        await self._db.commit()

    async def get(self, assignment_id: str) -> RoleAssignment | None:
        cursor = await self._db.execute(
            "SELECT * FROM role_assignments WHERE id = ?", (assignment_id,),
        )
        row = await cursor.fetchone()
        return self._row_to_entity(row) if row else None

    async def list_for_project(
        self, project_id: str, include_retired: bool = False,
    ) -> list[RoleAssignment]:
        if include_retired:
            cursor = await self._db.execute(
                "SELECT * FROM role_assignments WHERE project_id = ? ORDER BY assigned_at",
                (project_id,),
            )
        else:
            cursor = await self._db.execute(
                """SELECT * FROM role_assignments
                   WHERE project_id = ? AND retired_at IS NULL
                   ORDER BY assigned_at""",
                (project_id,),
            )
        rows = await cursor.fetchall()
        return [self._row_to_entity(row) for row in rows]

    async def list_all(self, include_retired: bool = False) -> list[RoleAssignment]:
        if include_retired:
            cursor = await self._db.execute(
                "SELECT * FROM role_assignments ORDER BY assigned_at",
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM role_assignments WHERE retired_at IS NULL ORDER BY assigned_at",
            )
        rows = await cursor.fetchall()
        return [self._row_to_entity(row) for row in rows]

    async def find(
        self, project_id: str, role: AgentRole,
    ) -> RoleAssignment | None:
        cursor = await self._db.execute(
            """SELECT * FROM role_assignments
               WHERE project_id = ? AND role = ? AND retired_at IS NULL
               ORDER BY assigned_at DESC LIMIT 1""",
            (project_id, role.value),
        )
        row = await cursor.fetchone()
        return self._row_to_entity(row) if row else None

    async def codenames_in_use(self) -> set[str]:
        cursor = await self._db.execute(
            "SELECT codename FROM role_assignments WHERE retired_at IS NULL",
        )
        rows = await cursor.fetchall()
        return {row["codename"] for row in rows}

    @staticmethod
    def _row_to_entity(row) -> RoleAssignment:
        config_raw = row["config_json"] if row["config_json"] else "{}"
        try:
            config = json.loads(config_raw)
        except (TypeError, ValueError):
            config = {}
        return RoleAssignment(
            id=row["id"],
            project_id=row["project_id"],
            role=AgentRole.from_str(row["role"]),
            codename=row["codename"],
            assigned_at=datetime.fromisoformat(row["assigned_at"]),
            retired_at=datetime.fromisoformat(row["retired_at"]) if row["retired_at"] else None,
            config=config,
        )
