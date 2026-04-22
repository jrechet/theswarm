"""SQLite repository for deployments."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.sre.entities import Deployment
from theswarm.domain.sre.value_objects import DeployStatus


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def _dt_opt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class SQLiteDeploymentRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, d: Deployment) -> Deployment:
        await self._db.execute(
            """INSERT INTO deployments
                (id, project_id, environment, version, status, notes,
                 triggered_by, started_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                d.id, d.project_id, d.environment, d.version, d.status.value,
                d.notes, d.triggered_by, d.started_at.isoformat(),
                d.completed_at.isoformat() if d.completed_at else None,
            ),
        )
        await self._db.commit()
        return d

    async def update_status(
        self, deployment_id: str, status: DeployStatus,
        completed_at: datetime | None, notes: str = "",
    ) -> None:
        if notes:
            await self._db.execute(
                """UPDATE deployments
                      SET status=?, completed_at=?, notes=?
                    WHERE id=?""",
                (
                    status.value,
                    completed_at.isoformat() if completed_at else None,
                    notes, deployment_id,
                ),
            )
        else:
            await self._db.execute(
                """UPDATE deployments
                      SET status=?, completed_at=?
                    WHERE id=?""",
                (
                    status.value,
                    completed_at.isoformat() if completed_at else None,
                    deployment_id,
                ),
            )
        await self._db.commit()

    async def get(self, deployment_id: str) -> Deployment | None:
        cur = await self._db.execute(
            "SELECT * FROM deployments WHERE id=?", (deployment_id,),
        )
        row = await cur.fetchone()
        return _row_to_deploy(row) if row else None

    async def list_for_project(
        self, project_id: str, limit: int = 20,
    ) -> list[Deployment]:
        cur = await self._db.execute(
            """SELECT * FROM deployments WHERE project_id=?
                ORDER BY started_at DESC LIMIT ?""",
            (project_id, limit),
        )
        return [_row_to_deploy(r) for r in await cur.fetchall()]


def _row_to_deploy(row) -> Deployment:
    return Deployment(
        id=row["id"],
        project_id=row["project_id"],
        environment=row["environment"],
        version=row["version"],
        status=DeployStatus(row["status"]),
        notes=row["notes"],
        triggered_by=row["triggered_by"],
        started_at=_dt(row["started_at"]),
        completed_at=_dt_opt(row["completed_at"]),
    )
