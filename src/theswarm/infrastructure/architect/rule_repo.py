"""SQLite repository for PavedRoadRule (Phase K)."""

from __future__ import annotations

from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.architect.entities import PavedRoadRule
from theswarm.domain.architect.value_objects import RuleSeverity


def _dt(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


def _tags_to_text(tags: tuple[str, ...]) -> str:
    return ",".join(t.strip() for t in tags if t.strip())


def _text_to_tags(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    return tuple(t for t in (s.strip() for s in text.split(",")) if t)


class SQLitePavedRoadRuleRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, r: PavedRoadRule) -> PavedRoadRule:
        await self._db.execute(
            """INSERT INTO paved_road_rules
                (id, name, rule, rationale, severity, tags,
                 created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(name) DO UPDATE SET
                   rule=excluded.rule,
                   rationale=excluded.rationale,
                   severity=excluded.severity,
                   tags=excluded.tags,
                   updated_at=excluded.updated_at""",
            (
                r.id, r.name, r.rule, r.rationale, r.severity.value,
                _tags_to_text(r.tags),
                r.created_at.isoformat(), r.updated_at.isoformat(),
            ),
        )
        await self._db.commit()
        got = await self.get_for_name(r.name)
        return got if got is not None else r

    async def get_for_name(self, name: str) -> PavedRoadRule | None:
        cur = await self._db.execute(
            "SELECT * FROM paved_road_rules WHERE name=?", (name,),
        )
        row = await cur.fetchone()
        return _row_to_rule(row) if row else None

    async def list_all(self) -> list[PavedRoadRule]:
        cur = await self._db.execute(
            "SELECT * FROM paved_road_rules ORDER BY severity DESC, name",
        )
        return [_row_to_rule(r) for r in await cur.fetchall()]


def _row_to_rule(row) -> PavedRoadRule:
    return PavedRoadRule(
        id=row["id"],
        name=row["name"],
        rule=row["rule"],
        rationale=row["rationale"],
        severity=RuleSeverity(row["severity"]),
        tags=_text_to_tags(row["tags"]),
        created_at=_dt(row["created_at"]),
        updated_at=_dt(row["updated_at"]),
    )
