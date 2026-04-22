"""SQLite repository for demo outcome cards."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.qa.entities import OutcomeCard, StoryAcceptance


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def _acceptance_to_json(items: tuple[StoryAcceptance, ...]) -> str:
    return json.dumps(
        [
            {"text": a.text, "passed": a.passed, "evidence": a.evidence}
            for a in items
        ]
    )


def _acceptance_from_json(raw: str | None) -> tuple[StoryAcceptance, ...]:
    if not raw:
        return ()
    data = json.loads(raw)
    return tuple(
        StoryAcceptance(
            text=d.get("text", ""),
            passed=bool(d.get("passed", False)),
            evidence=d.get("evidence", ""),
        )
        for d in data
    )


class SQLiteOutcomeCardRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def add(self, card: OutcomeCard) -> OutcomeCard:
        await self._db.execute(
            """INSERT INTO qa_outcome_cards
                (id, project_id, story_id, title, acceptance_json,
                 metric_name, metric_before, metric_after,
                 screenshot_path, narrated_video_path, summary, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                card.id,
                card.project_id,
                card.story_id,
                card.title,
                _acceptance_to_json(card.acceptance),
                card.metric_name,
                card.metric_before,
                card.metric_after,
                card.screenshot_path,
                card.narrated_video_path,
                card.summary,
                card.created_at.isoformat(),
            ),
        )
        await self._db.commit()
        return card

    async def list_for_project(
        self, project_id: str, *, limit: int = 20,
    ) -> list[OutcomeCard]:
        cur = await self._db.execute(
            "SELECT * FROM qa_outcome_cards WHERE project_id=? "
            "ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        )
        return [_row_to_card(r) for r in await cur.fetchall()]

    async def get(self, card_id: str) -> OutcomeCard | None:
        cur = await self._db.execute(
            "SELECT * FROM qa_outcome_cards WHERE id=?", (card_id,),
        )
        row = await cur.fetchone()
        return _row_to_card(row) if row else None


def _row_to_card(row) -> OutcomeCard:
    return OutcomeCard(
        id=row["id"],
        project_id=row["project_id"],
        story_id=row["story_id"],
        title=row["title"],
        acceptance=_acceptance_from_json(row["acceptance_json"]),
        metric_name=row["metric_name"],
        metric_before=row["metric_before"],
        metric_after=row["metric_after"],
        screenshot_path=row["screenshot_path"],
        narrated_video_path=row["narrated_video_path"],
        summary=row["summary"],
        created_at=_dt(row["created_at"]),
    )
