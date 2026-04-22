"""SQLite repository for refactor preflight checks."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.dev_rigour.entities import RefactorPreflight
from theswarm.domain.dev_rigour.value_objects import PreflightDecision


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteRefactorPreflightRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, preflight: RefactorPreflight) -> RefactorPreflight:
        await self._db.execute(
            """INSERT INTO dev_refactor_preflights
                (id, project_id, pr_url, task_id, codename,
                 deletion_lines, files_touched_json, callers_checked_json,
                 decision, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                preflight.id,
                preflight.project_id,
                preflight.pr_url,
                preflight.task_id,
                preflight.codename,
                preflight.deletion_lines,
                json.dumps(list(preflight.files_touched)),
                json.dumps(list(preflight.callers_checked)),
                preflight.decision.value,
                preflight.reason,
                preflight.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return preflight

    async def list_for_project(
        self, project_id: str, *, limit: int = 20,
    ) -> list[RefactorPreflight]:
        cur = await self._db.execute(
            "SELECT * FROM dev_refactor_preflights WHERE project_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )
        return [_row_to_preflight(r) for r in await cur.fetchall()]


def _row_to_preflight(row) -> RefactorPreflight:
    return RefactorPreflight(
        id=row["id"],
        project_id=row["project_id"],
        pr_url=row["pr_url"],
        task_id=row["task_id"],
        codename=row["codename"],
        deletion_lines=row["deletion_lines"],
        files_touched=tuple(json.loads(row["files_touched_json"] or "[]")),
        callers_checked=tuple(json.loads(row["callers_checked_json"] or "[]")),
        decision=PreflightDecision(row["decision"]),
        reason=row["reason"],
        created_at=_dt(row["created_at"]),
    )
