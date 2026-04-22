"""SQLite repository for dependency radar findings."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.techlead.entities import DepFinding
from theswarm.domain.techlead.value_objects import DepSeverity

_SEV_ORDER = {
    DepSeverity.CRITICAL: 0,
    DepSeverity.HIGH: 1,
    DepSeverity.MEDIUM: 2,
    DepSeverity.LOW: 3,
    DepSeverity.INFO: 4,
}


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteDepFindingRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, finding: DepFinding) -> DepFinding:
        """Unique on (project_id, package, advisory_id). Refresh severity/summary."""
        cur = await self._db.execute(
            "SELECT id FROM techlead_dep_findings "
            "WHERE project_id=? AND package=? AND advisory_id=?",
            (finding.project_id, finding.package, finding.advisory_id),
        )
        row = await cur.fetchone()
        if row:
            await self._db.execute(
                """UPDATE techlead_dep_findings
                    SET installed_version=?, severity=?, summary=?,
                        fixed_version=?, source=?, url=?, observed_at=?
                    WHERE id=?""",
                (
                    finding.installed_version,
                    finding.severity.value,
                    finding.summary,
                    finding.fixed_version,
                    finding.source,
                    finding.url,
                    finding.observed_at.isoformat(),
                    row["id"],
                ),
            )
            await self._db.commit()
            got = await self.get(row["id"])
            return got or finding

        await self._db.execute(
            """INSERT INTO techlead_dep_findings
                (id, project_id, package, installed_version, advisory_id,
                 severity, summary, fixed_version, source, url, observed_at,
                 dismissed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                finding.id,
                finding.project_id,
                finding.package,
                finding.installed_version,
                finding.advisory_id,
                finding.severity.value,
                finding.summary,
                finding.fixed_version,
                finding.source,
                finding.url,
                finding.observed_at.isoformat(),
                1 if finding.dismissed else 0,
            ),
        )
        await self._db.commit()
        return finding

    async def get(self, finding_id: str) -> DepFinding | None:
        cur = await self._db.execute(
            "SELECT * FROM techlead_dep_findings WHERE id=?", (finding_id,),
        )
        row = await cur.fetchone()
        return _row_to_finding(row) if row else None

    async def list_for_project(
        self,
        project_id: str,
        *,
        include_dismissed: bool = False,
    ) -> list[DepFinding]:
        if include_dismissed:
            cur = await self._db.execute(
                "SELECT * FROM techlead_dep_findings WHERE project_id=?",
                (project_id,),
            )
        else:
            cur = await self._db.execute(
                "SELECT * FROM techlead_dep_findings "
                "WHERE project_id=? AND dismissed=0",
                (project_id,),
            )
        findings = [_row_to_finding(r) for r in await cur.fetchall()]
        findings.sort(key=lambda f: (_SEV_ORDER[f.severity], -f.observed_at.timestamp()))
        return findings

    async def dismiss(self, finding_id: str) -> DepFinding | None:
        await self._db.execute(
            "UPDATE techlead_dep_findings SET dismissed=1 WHERE id=?",
            (finding_id,),
        )
        await self._db.commit()
        return await self.get(finding_id)


def _row_to_finding(row) -> DepFinding:
    return DepFinding(
        id=row["id"],
        project_id=row["project_id"],
        package=row["package"],
        installed_version=row["installed_version"],
        advisory_id=row["advisory_id"],
        severity=DepSeverity(row["severity"]),
        summary=row["summary"],
        fixed_version=row["fixed_version"],
        source=row["source"],
        url=row["url"],
        observed_at=_dt(row["observed_at"]),
        dismissed=bool(row["dismissed"]),
    )
