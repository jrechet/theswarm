"""SQLite repository for Proposals."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import aiosqlite

from theswarm.domain.product.entities import Proposal
from theswarm.domain.product.value_objects import ProposalStatus


def _dt(value: str) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteProposalRepository:
    """Persistence for proposals. Dedup key prevents identical titles."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def upsert(self, proposal: Proposal) -> Proposal:
        """Insert or update by ``(project_id, dedup_key)``.

        If a row with the same dedup key already exists we keep the existing
        status (so a human decision is not overwritten by a refresh of the
        source). We do refresh evidence, confidence, and rationale.
        """
        dedup = Proposal.dedup_key(proposal.project_id, proposal.title)
        existing = await self._db.execute(
            "SELECT id, status, decided_at, decision_note, linked_story_id "
            "FROM product_proposals WHERE project_id=? AND dedup_key=?",
            (proposal.project_id, dedup),
        )
        row = await existing.fetchone()
        if row:
            await self._db.execute(
                """UPDATE product_proposals
                    SET summary=?, rationale=?, source_url=?, evidence_excerpt=?,
                        confidence=?, tags_json=?, metadata_json=?, codename=?
                    WHERE id=?""",
                (
                    proposal.summary,
                    proposal.rationale,
                    proposal.source_url,
                    proposal.evidence_excerpt,
                    proposal.confidence,
                    json.dumps(list(proposal.tags)),
                    json.dumps(dict(proposal.metadata)),
                    proposal.codename,
                    row["id"],
                ),
            )
            await self._db.commit()
            return await self.get(row["id"])  # type: ignore[return-value]

        await self._db.execute(
            """INSERT INTO product_proposals
                (id, project_id, dedup_key, title, summary, rationale,
                 source_url, evidence_excerpt, confidence, status, codename,
                 tags_json, metadata_json, created_at, decided_at,
                 decision_note, linked_story_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                proposal.id,
                proposal.project_id,
                dedup,
                proposal.title,
                proposal.summary,
                proposal.rationale,
                proposal.source_url,
                proposal.evidence_excerpt,
                proposal.confidence,
                proposal.status.value,
                proposal.codename,
                json.dumps(list(proposal.tags)),
                json.dumps(dict(proposal.metadata)),
                proposal.created_at.isoformat(),
                proposal.decided_at.isoformat() if proposal.decided_at else "",
                proposal.decision_note,
                proposal.linked_story_id,
            ),
        )
        await self._db.commit()
        return proposal

    async def get(self, proposal_id: str) -> Proposal | None:
        cur = await self._db.execute(
            "SELECT * FROM product_proposals WHERE id=?",
            (proposal_id,),
        )
        row = await cur.fetchone()
        return _row_to_proposal(row) if row else None

    async def list_for_project(
        self,
        project_id: str,
        *,
        statuses: tuple[ProposalStatus, ...] | None = None,
    ) -> list[Proposal]:
        if statuses is None:
            cur = await self._db.execute(
                "SELECT * FROM product_proposals WHERE project_id=? "
                "ORDER BY created_at DESC",
                (project_id,),
            )
        else:
            placeholders = ",".join(["?"] * len(statuses))
            cur = await self._db.execute(
                f"SELECT * FROM product_proposals WHERE project_id=? AND "
                f"status IN ({placeholders}) ORDER BY created_at DESC",
                (project_id, *(s.value for s in statuses)),
            )
        return [_row_to_proposal(r) for r in await cur.fetchall()]

    async def list_inbox(self, project_id: str) -> list[Proposal]:
        """Only proposals awaiting a decision."""
        return await self.list_for_project(
            project_id, statuses=(ProposalStatus.PROPOSED, ProposalStatus.ASKED),
        )

    async def decide(
        self,
        proposal_id: str,
        *,
        status: ProposalStatus,
        note: str = "",
        linked_story_id: str = "",
    ) -> Proposal | None:
        await self._db.execute(
            """UPDATE product_proposals
                SET status=?, decided_at=?, decision_note=?, linked_story_id=?
                WHERE id=?""",
            (status.value, _now_iso(), note, linked_story_id, proposal_id),
        )
        await self._db.commit()
        return await self.get(proposal_id)

    async def counts_by_status(self, project_id: str) -> dict[str, int]:
        cur = await self._db.execute(
            "SELECT status, COUNT(*) AS n FROM product_proposals "
            "WHERE project_id=? GROUP BY status",
            (project_id,),
        )
        return {r["status"]: int(r["n"]) for r in await cur.fetchall()}


def _row_to_proposal(row) -> Proposal:
    decided_iso = row["decided_at"]
    return Proposal(
        id=row["id"],
        project_id=row["project_id"],
        title=row["title"],
        summary=row["summary"],
        rationale=row["rationale"],
        source_url=row["source_url"],
        evidence_excerpt=row["evidence_excerpt"],
        confidence=float(row["confidence"]),
        status=ProposalStatus(row["status"]),
        codename=row["codename"],
        tags=tuple(json.loads(row["tags_json"] or "[]")),
        metadata=dict(json.loads(row["metadata_json"] or "{}")),
        created_at=_dt(row["created_at"]) or datetime.now(timezone.utc),
        decided_at=_dt(decided_iso) if decided_iso else None,
        decision_note=row["decision_note"],
        linked_story_id=row["linked_story_id"],
    )
