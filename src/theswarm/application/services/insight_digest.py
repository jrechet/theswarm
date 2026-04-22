"""Weekly insight digest generator.

Aggregates signals + proposals for the last 7 days and produces an
``InsightDigest`` with a short prose narrative. The narrative is rule-based
for now (deterministic, no LLM) so tests run offline; an LLM NLU port can be
swapped in later.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Protocol

from theswarm.domain.product.entities import (
    DigestItem,
    InsightDigest,
    Proposal,
    Signal,
)
from theswarm.domain.product.value_objects import (
    InsightKind,
    ProposalStatus,
    SignalKind,
    SignalSeverity,
)


class SignalSourcePort(Protocol):
    async def list_for_project(
        self, project_id: str, *, since: datetime | None = None,
        kinds=None, limit: int = 100,
    ) -> list[Signal]: ...


class ProposalSourcePort(Protocol):
    async def list_for_project(
        self, project_id: str, *, statuses=None,
    ) -> list[Proposal]: ...


class DigestRepoPort(Protocol):
    async def save(self, digest: InsightDigest) -> InsightDigest: ...


class InsightDigestService:
    """Build and persist a weekly insight digest."""

    def __init__(
        self,
        signal_repo: SignalSourcePort,
        proposal_repo: ProposalSourcePort,
        digest_repo: DigestRepoPort,
    ) -> None:
        self._signals = signal_repo
        self._proposals = proposal_repo
        self._digests = digest_repo

    async def generate(
        self, *, project_id: str, now: datetime | None = None,
    ) -> InsightDigest:
        now = now or datetime.now(timezone.utc)
        week_start = now - timedelta(days=7)
        signals = await self._signals.list_for_project(
            project_id, since=week_start, limit=200,
        )
        proposals = await self._proposals.list_for_project(project_id)
        recent_props = [
            p for p in proposals if p.created_at >= week_start
        ]

        items: list[DigestItem] = []
        for s in signals:
            items.append(
                DigestItem(
                    kind=_signal_to_kind(s),
                    headline=s.title,
                    body=s.body[:240],
                    source_url=s.source_url,
                ),
            )
        for p in recent_props:
            items.append(
                DigestItem(
                    kind=InsightKind.USER_REQUEST,
                    headline=f"Proposal: {p.title}",
                    body=p.rationale or p.summary[:240],
                    source_url=p.source_url,
                ),
            )

        narrative = _narrative(signals, recent_props)
        digest = InsightDigest(
            id=InsightDigest.new_id(),
            project_id=project_id,
            week_start=week_start,
            items=tuple(items),
            narrative=narrative,
        )
        await self._digests.save(digest)
        return digest


def _signal_to_kind(s: Signal) -> InsightKind:
    if s.severity is SignalSeverity.THREAT:
        return InsightKind.RISK
    if s.kind is SignalKind.COMPETITOR:
        return InsightKind.COMPETITOR_MOVE
    if s.kind is SignalKind.CUSTOMER:
        return InsightKind.USER_REQUEST
    return InsightKind.TREND


def _narrative(signals: list[Signal], proposals: list[Proposal]) -> str:
    if not signals and not proposals:
        return "Quiet week — no new signals or proposals."
    kinds = Counter(s.kind.value for s in signals)
    severities = Counter(s.severity.value for s in signals)
    parts: list[str] = []
    if signals:
        parts.append(
            f"{len(signals)} new signals "
            f"({', '.join(f'{k}: {v}' for k, v in kinds.most_common())}).",
        )
    threats = severities.get(SignalSeverity.THREAT.value, 0)
    if threats:
        parts.append(f"{threats} flagged as threats.")
    approved = sum(
        1 for p in proposals if p.status is ProposalStatus.APPROVED
    )
    pending = sum(
        1 for p in proposals if p.status is ProposalStatus.PROPOSED
    )
    if proposals:
        parts.append(
            f"{len(proposals)} proposals ({approved} approved, {pending} pending).",
        )
    return " ".join(parts)
