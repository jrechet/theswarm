"""SQLite repository for recorded review verdicts (calibration input)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.techlead.entities import ReviewVerdict
from theswarm.domain.techlead.value_objects import ReviewDecision, ReviewOutcome


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteReviewVerdictRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def record(self, verdict: ReviewVerdict) -> ReviewVerdict:
        await self._db.execute(
            """INSERT INTO techlead_review_verdicts
                (id, project_id, pr_url, reviewer_codename, decision, severity,
                 override_reason, second_opinion, outcome, outcome_note,
                 created_at, outcome_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                verdict.id,
                verdict.project_id,
                verdict.pr_url,
                verdict.reviewer_codename,
                verdict.decision.value,
                verdict.severity,
                verdict.override_reason,
                1 if verdict.second_opinion else 0,
                verdict.outcome.value,
                verdict.outcome_note,
                verdict.created_at.isoformat(),
                verdict.outcome_at.isoformat() if verdict.outcome_at else None,
            ),
        )
        await self._db.commit()
        return verdict

    async def get(self, verdict_id: str) -> ReviewVerdict | None:
        cur = await self._db.execute(
            "SELECT * FROM techlead_review_verdicts WHERE id=?", (verdict_id,),
        )
        row = await cur.fetchone()
        return _row_to_verdict(row) if row else None

    async def set_outcome(
        self,
        verdict_id: str,
        outcome: ReviewOutcome,
        note: str = "",
    ) -> ReviewVerdict | None:
        await self._db.execute(
            """UPDATE techlead_review_verdicts
                SET outcome=?, outcome_note=?, outcome_at=?
                WHERE id=?""",
            (outcome.value, note, _now_iso(), verdict_id),
        )
        await self._db.commit()
        return await self.get(verdict_id)

    async def list_for_project(
        self,
        project_id: str,
        limit: int = 100,
    ) -> list[ReviewVerdict]:
        cur = await self._db.execute(
            "SELECT * FROM techlead_review_verdicts WHERE project_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )
        return [_row_to_verdict(r) for r in await cur.fetchall()]


def _row_to_verdict(row) -> ReviewVerdict:
    return ReviewVerdict(
        id=row["id"],
        project_id=row["project_id"],
        pr_url=row["pr_url"],
        reviewer_codename=row["reviewer_codename"],
        decision=ReviewDecision(row["decision"]),
        severity=row["severity"],
        override_reason=row["override_reason"],
        second_opinion=bool(row["second_opinion"]),
        outcome=ReviewOutcome(row["outcome"]),
        outcome_note=row["outcome_note"],
        created_at=_dt(row["created_at"]) or datetime.now(timezone.utc),
        outcome_at=_dt(row["outcome_at"]),
    )
