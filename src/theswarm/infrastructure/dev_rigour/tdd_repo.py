"""SQLite repository for TDD artifacts (RED→GREEN)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.dev_rigour.entities import TddArtifact
from theswarm.domain.dev_rigour.value_objects import TddPhase


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteTddArtifactRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, artifact: TddArtifact) -> TddArtifact:
        """Insert or update by (project_id, task_id)."""
        existing = await self.get_for_task(artifact.project_id, artifact.task_id)
        if existing is None:
            await self._db.execute(
                """INSERT INTO tdd_artifacts
                    (id, project_id, task_id, codename, phase,
                     test_files_json, red_commit, green_commit, notes,
                     created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    artifact.id,
                    artifact.project_id,
                    artifact.task_id,
                    artifact.codename,
                    artifact.phase.value,
                    json.dumps(list(artifact.test_files)),
                    artifact.red_commit,
                    artifact.green_commit,
                    artifact.notes,
                    artifact.created_at.isoformat(),
                    artifact.updated_at.isoformat(),
                ),
            )
        else:
            await self._db.execute(
                """UPDATE tdd_artifacts
                      SET codename=?, phase=?, test_files_json=?,
                          red_commit=?, green_commit=?, notes=?, updated_at=?
                    WHERE project_id=? AND task_id=?""",
                (
                    artifact.codename,
                    artifact.phase.value,
                    json.dumps(list(artifact.test_files)),
                    artifact.red_commit,
                    artifact.green_commit,
                    artifact.notes,
                    artifact.updated_at.isoformat(),
                    artifact.project_id,
                    artifact.task_id,
                ),
            )
        await self._db.commit()
        return artifact

    async def get_for_task(
        self, project_id: str, task_id: str,
    ) -> TddArtifact | None:
        cur = await self._db.execute(
            "SELECT * FROM tdd_artifacts WHERE project_id=? AND task_id=?",
            (project_id, task_id),
        )
        row = await cur.fetchone()
        return _row_to_artifact(row) if row else None

    async def list_for_project(self, project_id: str) -> list[TddArtifact]:
        cur = await self._db.execute(
            "SELECT * FROM tdd_artifacts WHERE project_id=? "
            "ORDER BY updated_at DESC",
            (project_id,),
        )
        return [_row_to_artifact(r) for r in await cur.fetchall()]


def _row_to_artifact(row) -> TddArtifact:
    return TddArtifact(
        id=row["id"],
        project_id=row["project_id"],
        task_id=row["task_id"],
        codename=row["codename"],
        phase=TddPhase(row["phase"]),
        test_files=tuple(json.loads(row["test_files_json"] or "[]")),
        red_commit=row["red_commit"],
        green_commit=row["green_commit"],
        notes=row["notes"],
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
