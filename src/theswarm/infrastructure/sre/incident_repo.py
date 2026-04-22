"""SQLite repository for incidents."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.sre.entities import Incident
from theswarm.domain.sre.value_objects import IncidentSeverity, IncidentStatus


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def _dt_opt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class SQLiteIncidentRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, i: Incident) -> Incident:
        await self._db.execute(
            """INSERT INTO incidents
                (id, project_id, title, severity, status, summary,
                 timeline_json, postmortem, detected_at, mitigated_at, resolved_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                i.id, i.project_id, i.title, i.severity.value, i.status.value,
                i.summary, json.dumps(list(i.timeline)), i.postmortem,
                i.detected_at.isoformat(),
                i.mitigated_at.isoformat() if i.mitigated_at else None,
                i.resolved_at.isoformat() if i.resolved_at else None,
            ),
        )
        await self._db.commit()
        return i

    async def update(self, i: Incident) -> None:
        await self._db.execute(
            """UPDATE incidents
                  SET status=?, summary=?, timeline_json=?, postmortem=?,
                      mitigated_at=?, resolved_at=?
                WHERE id=?""",
            (
                i.status.value, i.summary, json.dumps(list(i.timeline)),
                i.postmortem,
                i.mitigated_at.isoformat() if i.mitigated_at else None,
                i.resolved_at.isoformat() if i.resolved_at else None,
                i.id,
            ),
        )
        await self._db.commit()

    async def get(self, incident_id: str) -> Incident | None:
        cur = await self._db.execute(
            "SELECT * FROM incidents WHERE id=?", (incident_id,),
        )
        row = await cur.fetchone()
        return _row_to_incident(row) if row else None

    async def list_for_project(
        self, project_id: str, open_only: bool = False,
    ) -> list[Incident]:
        if open_only:
            cur = await self._db.execute(
                """SELECT * FROM incidents
                    WHERE project_id=? AND status IN ('open','triaged','mitigated')
                    ORDER BY detected_at DESC""",
                (project_id,),
            )
        else:
            cur = await self._db.execute(
                """SELECT * FROM incidents WHERE project_id=?
                    ORDER BY detected_at DESC""",
                (project_id,),
            )
        return [_row_to_incident(r) for r in await cur.fetchall()]


def _row_to_incident(row) -> Incident:
    timeline = tuple(json.loads(row["timeline_json"] or "[]"))
    return Incident(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        severity=IncidentSeverity(row["severity"]),
        status=IncidentStatus(row["status"]),
        summary=row["summary"],
        timeline=timeline,
        postmortem=row["postmortem"],
        detected_at=_dt(row["detected_at"]),
        mitigated_at=_dt_opt(row["mitigated_at"]),
        resolved_at=_dt_opt(row["resolved_at"]),
    )
