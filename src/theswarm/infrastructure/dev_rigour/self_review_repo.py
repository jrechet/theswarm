"""SQLite repository for Dev self-reviews."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.dev_rigour.entities import SelfReview, SelfReviewFinding
from theswarm.domain.dev_rigour.value_objects import FindingSeverity


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def _findings_to_json(findings: tuple[SelfReviewFinding, ...]) -> str:
    return json.dumps(
        [
            {
                "severity": f.severity.value,
                "category": f.category,
                "message": f.message,
                "waived": f.waived,
                "waive_reason": f.waive_reason,
            }
            for f in findings
        ]
    )


def _findings_from_json(raw: str | None) -> tuple[SelfReviewFinding, ...]:
    if not raw:
        return ()
    data = json.loads(raw)
    return tuple(
        SelfReviewFinding(
            severity=FindingSeverity(d.get("severity", "low")),
            category=d.get("category", ""),
            message=d.get("message", ""),
            waived=bool(d.get("waived", False)),
            waive_reason=d.get("waive_reason", ""),
        )
        for d in data
    )


class SQLiteSelfReviewRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, review: SelfReview) -> SelfReview:
        await self._db.execute(
            """INSERT INTO dev_self_reviews
                (id, project_id, pr_url, task_id, codename,
                 findings_json, summary, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                review.id,
                review.project_id,
                review.pr_url,
                review.task_id,
                review.codename,
                _findings_to_json(review.findings),
                review.summary,
                review.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return review

    async def list_for_project(
        self, project_id: str, *, limit: int = 20,
    ) -> list[SelfReview]:
        cur = await self._db.execute(
            "SELECT * FROM dev_self_reviews WHERE project_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )
        return [_row_to_review(r) for r in await cur.fetchall()]


def _row_to_review(row) -> SelfReview:
    return SelfReview(
        id=row["id"],
        project_id=row["project_id"],
        pr_url=row["pr_url"],
        task_id=row["task_id"],
        codename=row["codename"],
        findings=_findings_from_json(row["findings_json"]),
        summary=row["summary"],
        created_at=_dt(row["created_at"]),
    )
