"""DevOps proposals (D3, migration v035): raised, decided, run — kept."""

from __future__ import annotations

from datetime import datetime

import aiosqlite

from theswarm.domain.ops.proposals import OPEN, Proposal


class SQLiteProposalRepository:
    COLUMNS = ("id", "kind", "host", "title", "why", "command", "finding_key", "status", "result", "decided_by",
               "created_at", "decided_at", "ran_at")

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def get(self, proposal_id: str) -> Proposal | None:
        cursor = await self._db.execute("SELECT * FROM ops_proposals WHERE id = ?", (proposal_id,))
        row = await cursor.fetchone()
        return self._row(row) if row else None

    async def list_open(self) -> list[Proposal]:
        """Proposed and approved, oldest first: what waits for the owner, what waits to run."""
        marks = ", ".join("?" for _ in OPEN)
        cursor = await self._db.execute(
            f"SELECT * FROM ops_proposals WHERE status IN ({marks}) ORDER BY created_at ASC", OPEN,
        )
        return [self._row(r) for r in await cursor.fetchall()]

    async def list_recent(self, limit: int = 20) -> list[Proposal]:
        cursor = await self._db.execute("SELECT * FROM ops_proposals ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._row(r) for r in await cursor.fetchall()]

    async def save(self, proposal: Proposal) -> None:
        await self._db.execute(
            """INSERT INTO ops_proposals
               (id, kind, host, title, why, command, finding_key, status, result, decided_by, created_at, decided_at, ran_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 status = excluded.status, result = excluded.result, decided_by = excluded.decided_by,
                 decided_at = excluded.decided_at, ran_at = excluded.ran_at""",
            (proposal.id, proposal.kind, proposal.host, proposal.title, proposal.why, proposal.command,
             proposal.finding_key, proposal.status, proposal.result, proposal.decided_by,
             proposal.created_at.isoformat(), proposal.decided_at.isoformat() if proposal.decided_at else None,
             proposal.ran_at.isoformat() if proposal.ran_at else None),
        )
        await self._db.commit()

    @staticmethod
    def _row(row) -> Proposal:
        when = lambda v: datetime.fromisoformat(v) if v else None  # noqa: E731
        return Proposal(
            id=row["id"], kind=row["kind"], host=row["host"], title=row["title"], why=row["why"],
            command=row["command"], finding_key=row["finding_key"], status=row["status"], result=row["result"],
            decided_by=row["decided_by"], created_at=datetime.fromisoformat(row["created_at"]),
            decided_at=when(row["decided_at"]), ran_at=when(row["ran_at"]),
        )
