"""Proposal lifecycle service.

Ingests signals (competitor moves, ecosystem trends, customer requests) and
turns them into triage-ready proposals in the PO inbox. Handles human
decisions (Approve / Reject / Defer / Ask) and runs the policy filter before
a proposal can be approved into a story.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Protocol

from theswarm.application.services.policy_filter import PolicyFilter, PolicyVerdict
from theswarm.domain.product.entities import Proposal, Signal
from theswarm.domain.product.value_objects import (
    PolicyDecision,
    ProposalStatus,
    SignalKind,
    SignalSeverity,
)

log = logging.getLogger(__name__)


class ProposalRepoPort(Protocol):
    async def upsert(self, proposal: Proposal) -> Proposal: ...
    async def get(self, proposal_id: str) -> Proposal | None: ...
    async def list_for_project(
        self, project_id: str, *, statuses=None,
    ) -> list[Proposal]: ...
    async def list_inbox(self, project_id: str) -> list[Proposal]: ...
    async def decide(
        self, proposal_id: str, *, status: ProposalStatus,
        note: str = "", linked_story_id: str = "",
    ) -> Proposal | None: ...


class SignalRepoPort(Protocol):
    async def record(self, signal: Signal) -> Signal: ...


@dataclass(frozen=True)
class DecisionResult:
    proposal: Proposal | None
    verdict: PolicyVerdict | None = None
    message: str = ""


class ProposalService:
    """Create, triage, and decide on Proposals."""

    def __init__(
        self,
        proposal_repo: ProposalRepoPort,
        policy_filter: PolicyFilter,
        signal_repo: SignalRepoPort | None = None,
    ) -> None:
        self._proposals = proposal_repo
        self._policy = policy_filter
        self._signals = signal_repo

    async def propose_from_signal(
        self,
        *,
        project_id: str,
        signal: Signal,
        codename: str = "",
        confidence: float = 0.6,
    ) -> Proposal:
        """Persist the signal and create a Proposal for the PO inbox."""
        if self._signals is not None:
            await self._signals.record(signal)
        title = signal.title.strip() or "(untitled opportunity)"
        proposal = Proposal(
            id=Proposal.new_id(),
            project_id=project_id,
            title=title,
            summary=signal.body[:400],
            rationale=_rationale_for(signal),
            source_url=signal.source_url,
            evidence_excerpt=signal.body[:800],
            confidence=confidence,
            status=ProposalStatus.PROPOSED,
            codename=codename,
            tags=signal.tags,
            metadata={
                "signal_id": signal.id,
                "signal_kind": signal.kind.value,
                "signal_severity": signal.severity.value,
            },
        )
        return await self._proposals.upsert(proposal)

    async def list_inbox(self, project_id: str) -> list[Proposal]:
        return await self._proposals.list_inbox(project_id)

    async def approve(
        self, proposal_id: str, *, note: str = "", linked_story_id: str = "",
    ) -> DecisionResult:
        """Approve a proposal, subject to policy filter."""
        proposal = await self._proposals.get(proposal_id)
        if proposal is None:
            return DecisionResult(proposal=None, message="not found")
        verdict = await self._policy.evaluate(
            project_id=proposal.project_id,
            text=f"{proposal.title}\n{proposal.summary}\n{proposal.rationale}",
        )
        if verdict.decision is PolicyDecision.BLOCK:
            log.warning("proposal %s blocked by policy", proposal_id)
            updated = await self._proposals.decide(
                proposal_id,
                status=ProposalStatus.REJECTED,
                note=f"policy block: {verdict.reason}",
            )
            return DecisionResult(
                proposal=updated, verdict=verdict,
                message="rejected by policy",
            )
        if verdict.decision is PolicyDecision.REVIEW and not note:
            updated = await self._proposals.decide(
                proposal_id,
                status=ProposalStatus.ASKED,
                note=f"policy review required: {verdict.reason}",
            )
            return DecisionResult(
                proposal=updated, verdict=verdict,
                message="escalated for human review",
            )
        updated = await self._proposals.decide(
            proposal_id,
            status=ProposalStatus.APPROVED,
            note=note,
            linked_story_id=linked_story_id,
        )
        return DecisionResult(proposal=updated, verdict=verdict, message="approved")

    async def reject(
        self, proposal_id: str, *, note: str = "",
    ) -> DecisionResult:
        updated = await self._proposals.decide(
            proposal_id, status=ProposalStatus.REJECTED, note=note,
        )
        return DecisionResult(proposal=updated, message="rejected")

    async def defer(
        self, proposal_id: str, *, note: str = "",
    ) -> DecisionResult:
        updated = await self._proposals.decide(
            proposal_id, status=ProposalStatus.DEFERRED, note=note,
        )
        return DecisionResult(proposal=updated, message="deferred")

    async def ask(
        self, proposal_id: str, *, note: str = "",
    ) -> DecisionResult:
        updated = await self._proposals.decide(
            proposal_id, status=ProposalStatus.ASKED, note=note,
        )
        return DecisionResult(proposal=updated, message="asked")


def _rationale_for(signal: Signal) -> str:
    prefix = {
        SignalKind.COMPETITOR: "Competitor activity",
        SignalKind.ECOSYSTEM: "Ecosystem trend",
        SignalKind.CUSTOMER: "Customer request",
        SignalKind.INTERNAL: "Internal observation",
    }.get(signal.kind, "Signal")
    tone = {
        SignalSeverity.THREAT: "Risk if ignored.",
        SignalSeverity.OPPORTUNITY: "Potential upside.",
        SignalSeverity.INFO: "Context for upcoming planning.",
        SignalSeverity.NOISE: "Low confidence — verify.",
    }.get(signal.severity, "")
    return f"{prefix}: {signal.title.strip()}. {tone}".strip()
