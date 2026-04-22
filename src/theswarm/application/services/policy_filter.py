"""Policy filter — hard rules applied to generated stories / proposals.

Usage:

    filter = PolicyFilter(policy_repo)
    decision = await filter.evaluate(project_id="demo", text="crypto exchange")
    if decision.decision is PolicyDecision.BLOCK: ...

This is the single point where PO-authored rules gate content. The filter
returns a structured decision (ALLOW / REVIEW / BLOCK) plus the matched
terms so the UI can explain the outcome.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from theswarm.domain.product.value_objects import PolicyDecision

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PolicyVerdict:
    decision: PolicyDecision
    matched_banned: tuple[str, ...] = ()
    matched_review: tuple[str, ...] = ()
    reason: str = ""


class PolicyFilter:
    """Evaluate a candidate text against a project's policy."""

    def __init__(self, policy_repo) -> None:
        self._policies = policy_repo

    async def evaluate(self, *, project_id: str, text: str) -> PolicyVerdict:
        policy = await self._policies.get(project_id)
        if policy is None:
            return PolicyVerdict(decision=PolicyDecision.ALLOW)
        lowered = text.lower()
        banned = tuple(
            term for term in policy.banned_terms
            if term and term.lower() in lowered
        )
        review = tuple(
            term for term in policy.require_review_terms
            if term and term.lower() in lowered
        )
        if banned:
            return PolicyVerdict(
                decision=PolicyDecision.BLOCK,
                matched_banned=banned,
                matched_review=review,
                reason=f"blocked by banned term(s): {', '.join(banned)}",
            )
        if review:
            return PolicyVerdict(
                decision=PolicyDecision.REVIEW,
                matched_review=review,
                reason=f"requires human review: {', '.join(review)}",
            )
        return PolicyVerdict(decision=PolicyDecision.ALLOW)
