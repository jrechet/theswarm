"""SQLite repository for OKRs + KeyResults."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.product.entities import KeyResult, OKR


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt(value: str) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(value)


class SQLiteOKRRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def create(self, okr: OKR) -> OKR:
        await self._db.execute(
            """INSERT INTO product_okrs
                (id, project_id, objective, quarter, owner_codename,
                 created_at, updated_at, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                okr.id,
                okr.project_id,
                okr.objective,
                okr.quarter,
                okr.owner_codename,
                okr.created_at.isoformat(),
                okr.updated_at.isoformat(),
                1 if okr.active else 0,
            ),
        )
        for ordinal, kr in enumerate(okr.key_results):
            await self._write_kr(okr.id, kr, ordinal)
        await self._db.commit()
        return okr

    async def update(self, okr: OKR) -> OKR:
        await self._db.execute(
            """UPDATE product_okrs
                SET objective=?, quarter=?, owner_codename=?,
                    updated_at=?, active=?
                WHERE id=?""",
            (
                okr.objective,
                okr.quarter,
                okr.owner_codename,
                _now_iso(),
                1 if okr.active else 0,
                okr.id,
            ),
        )
        await self._db.execute(
            "DELETE FROM product_key_results WHERE okr_id=?", (okr.id,),
        )
        for ordinal, kr in enumerate(okr.key_results):
            await self._write_kr(okr.id, kr, ordinal)
        await self._db.commit()
        return await self.get(okr.id)  # type: ignore[return-value]

    async def _write_kr(self, okr_id: str, kr: KeyResult, ordinal: int) -> None:
        await self._db.execute(
            """INSERT INTO product_key_results
                (id, okr_id, description, target, baseline, current, progress, ordinal)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                kr.id,
                okr_id,
                kr.description,
                kr.target,
                kr.baseline,
                kr.current,
                kr.progress,
                ordinal,
            ),
        )

    async def get(self, okr_id: str) -> OKR | None:
        cur = await self._db.execute(
            "SELECT * FROM product_okrs WHERE id=?", (okr_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        kr_cur = await self._db.execute(
            "SELECT * FROM product_key_results WHERE okr_id=? ORDER BY ordinal",
            (okr_id,),
        )
        krs = tuple(
            KeyResult(
                id=r["id"],
                description=r["description"],
                target=r["target"],
                baseline=r["baseline"],
                current=r["current"],
                progress=float(r["progress"]),
            )
            for r in await kr_cur.fetchall()
        )
        return OKR(
            id=row["id"],
            project_id=row["project_id"],
            objective=row["objective"],
            key_results=krs,
            quarter=row["quarter"],
            owner_codename=row["owner_codename"],
            created_at=_dt(row["created_at"]),
            updated_at=_dt(row["updated_at"]),
            active=bool(row["active"]),
        )

    async def list_for_project(self, project_id: str, *, active_only: bool = True) -> list[OKR]:
        if active_only:
            cur = await self._db.execute(
                "SELECT id FROM product_okrs WHERE project_id=? AND active=1 "
                "ORDER BY created_at DESC",
                (project_id,),
            )
        else:
            cur = await self._db.execute(
                "SELECT id FROM product_okrs WHERE project_id=? "
                "ORDER BY created_at DESC",
                (project_id,),
            )
        ids = [r["id"] for r in await cur.fetchall()]
        result: list[OKR] = []
        for oid in ids:
            okr = await self.get(oid)
            if okr is not None:
                result.append(okr)
        return result

    async def retire(self, okr_id: str) -> None:
        await self._db.execute(
            "UPDATE product_okrs SET active=0, updated_at=? WHERE id=?",
            (_now_iso(), okr_id),
        )
        await self._db.commit()

    async def update_key_result_progress(
        self, okr_id: str, kr_id: str, *, current: str, progress: float,
    ) -> OKR | None:
        await self._db.execute(
            """UPDATE product_key_results
                SET current=?, progress=?
                WHERE id=? AND okr_id=?""",
            (current, progress, kr_id, okr_id),
        )
        await self._db.execute(
            "UPDATE product_okrs SET updated_at=? WHERE id=?",
            (_now_iso(), okr_id),
        )
        await self._db.commit()
        return await self.get(okr_id)
