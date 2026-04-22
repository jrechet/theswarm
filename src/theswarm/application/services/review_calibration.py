"""Review calibration — records reviewer verdicts plus eventual outcomes.

Calibration asks two questions of each past review:

- **False positive.** Did a REQUEST_CHANGES later ship cleanly (maybe with a
  pragmatic override)? If yes, the reviewer was over-strict.
- **False negative.** Did an APPROVE later need a revert or a patch?
  If yes, the reviewer missed something.

The service exposes simple rates for the dashboard to surface over time; it
does not try to "learn" anything — that's a later job that can consume this
history as prior.
"""

from __future__ import annotations

from dataclasses import dataclass

from theswarm.domain.techlead.entities import ReviewVerdict
from theswarm.domain.techlead.value_objects import ReviewDecision, ReviewOutcome
from theswarm.infrastructure.techlead.verdict_repo import (
    SQLiteReviewVerdictRepository,
)


@dataclass(frozen=True)
class CalibrationStats:
    total: int
    approved: int
    requested_changes: int
    commented: int
    reverted: int
    patch_needed: int
    clean: int
    false_positive_rate: float  # request_changes later overridden + clean
    false_negative_rate: float  # approved but reverted/patch-needed

    @property
    def signed(self) -> bool:
        return self.total > 0


class ReviewCalibrationService:
    def __init__(self, verdict_repo: SQLiteReviewVerdictRepository) -> None:
        self._verdicts = verdict_repo

    async def record(
        self,
        *,
        project_id: str,
        pr_url: str,
        reviewer_codename: str,
        decision: ReviewDecision,
        severity: str = "low",
        override_reason: str = "",
        second_opinion: bool = False,
    ) -> ReviewVerdict:
        verdict = ReviewVerdict(
            id=ReviewVerdict.new_id(),
            project_id=project_id,
            pr_url=pr_url,
            reviewer_codename=reviewer_codename,
            decision=decision,
            severity=severity,
            override_reason=override_reason,
            second_opinion=second_opinion,
        )
        return await self._verdicts.record(verdict)

    async def set_outcome(
        self,
        verdict_id: str,
        outcome: ReviewOutcome,
        note: str = "",
    ) -> ReviewVerdict | None:
        return await self._verdicts.set_outcome(verdict_id, outcome, note)

    async def stats(self, project_id: str) -> CalibrationStats:
        verdicts = await self._verdicts.list_for_project(project_id, limit=1000)
        total = len(verdicts)
        approved = sum(1 for v in verdicts if v.decision is ReviewDecision.APPROVE)
        requested = sum(
            1 for v in verdicts if v.decision is ReviewDecision.REQUEST_CHANGES
        )
        commented = sum(1 for v in verdicts if v.decision is ReviewDecision.COMMENT)
        reverted = sum(1 for v in verdicts if v.outcome is ReviewOutcome.REVERTED)
        patch_needed = sum(
            1 for v in verdicts if v.outcome is ReviewOutcome.PATCH_NEEDED
        )
        clean = sum(1 for v in verdicts if v.outcome is ReviewOutcome.CLEAN)

        # FP: changes requested but ended clean after override
        fp = sum(
            1
            for v in verdicts
            if v.decision is ReviewDecision.REQUEST_CHANGES
            and v.outcome is ReviewOutcome.CLEAN
            and v.override_reason
        )
        fp_rate = fp / requested if requested else 0.0
        # FN: approved but required intervention after the fact
        fn = sum(
            1
            for v in verdicts
            if v.decision is ReviewDecision.APPROVE
            and v.outcome in (ReviewOutcome.PATCH_NEEDED, ReviewOutcome.REVERTED)
        )
        fn_rate = fn / approved if approved else 0.0

        return CalibrationStats(
            total=total,
            approved=approved,
            requested_changes=requested,
            commented=commented,
            reverted=reverted,
            patch_needed=patch_needed,
            clean=clean,
            false_positive_rate=fp_rate,
            false_negative_rate=fn_rate,
        )
