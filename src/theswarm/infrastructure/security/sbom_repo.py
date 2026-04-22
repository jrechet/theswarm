"""SQLite repository for SBOM artifacts."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.security.entities import SBOMArtifact


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteSBOMRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, a: SBOMArtifact) -> SBOMArtifact:
        await self._db.execute(
            """INSERT INTO sbom_artifacts
                (id, project_id, cycle_id, tool, package_count,
                 license_summary, artifact_path, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                a.id, a.project_id, a.cycle_id, a.tool, a.package_count,
                a.license_summary, a.artifact_path, a.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return a

    async def latest_for_project(self, project_id: str) -> SBOMArtifact | None:
        cur = await self._db.execute(
            """SELECT * FROM sbom_artifacts WHERE project_id=?
                ORDER BY created_at DESC LIMIT 1""",
            (project_id,),
        )
        row = await cur.fetchone()
        return _row_to_sbom(row) if row else None

    async def list_for_project(self, project_id: str) -> list[SBOMArtifact]:
        cur = await self._db.execute(
            """SELECT * FROM sbom_artifacts WHERE project_id=?
                ORDER BY created_at DESC""",
            (project_id,),
        )
        return [_row_to_sbom(r) for r in await cur.fetchall()]


def _row_to_sbom(row) -> SBOMArtifact:
    return SBOMArtifact(
        id=row["id"],
        project_id=row["project_id"],
        cycle_id=row["cycle_id"],
        tool=row["tool"],
        package_count=row["package_count"],
        license_summary=row["license_summary"],
        artifact_path=row["artifact_path"],
        created_at=_dt(row["created_at"]),
    )
