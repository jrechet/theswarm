"""Read a pull request's CI before merging it.

The TechLead merged every APPROVE without looking, and branch protection
does not stop it on either repository the swarm works on: concert-tour-app's
main requires no status check, and TheSwarm's exempts the admin token the
swarm merges with. A red PR goes back to the Dev; a PR whose CI is still
running is waited for, bounded, then left open for the next pass.

The swarm's own `theswarm/review` status is its verdict, not CI, and is
left out. Cancelled, skipped, neutral and stale runs carry no signal. An
unreadable CI never blocks a merge: that was the behaviour before.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# How long a merge waits for CI still running. A review takes minutes, so a
# PR's CI is usually done before its merge; this covers the tail.
CI_WAIT_SECONDS = 300
CI_POLL_SECONDS = 20

# On the task issue, next to CHANGES_MARKER: why the PR came back.
CI_RED_MARKER = "<!-- swarm:ci-red -->"
CI_RED_SUMMARY = (
    "This PR was approved but its CI is red, so it was not merged. Read "
    "what the failing checks below report, reproduce it locally, fix it on "
    "this branch and push; do not start over."
)

_OWN_CONTEXTS = frozenset({"theswarm/review"})
_RED = frozenset({"failure", "error", "timed_out", "action_required", "startup_failure"})
_PENDING = frozenset({"pending", "queued", "in_progress", "waiting", "requested", "expected"})
_NO_SIGNAL = frozenset({"cancelled", "skipped", "neutral", "stale"})


@dataclass(frozen=True)
class CiVerdict:
    """green | red | pending | none, and the checks that failed."""

    state: str
    failing: tuple[dict, ...] = field(default_factory=tuple)


def ci_verdict(checks: list[dict]) -> CiVerdict:
    """What CI says about one commit, from its flattened statuses and check runs."""
    signals = [
        c for c in checks
        if c.get("name") not in _OWN_CONTEXTS and c.get("state") not in _NO_SIGNAL
    ]
    failing = tuple(c for c in signals if c.get("state") in _RED)
    if failing:
        return CiVerdict("red", failing)
    if any(c.get("state") in _PENDING for c in signals):
        return CiVerdict("pending")
    return CiVerdict("green" if signals else "none")


async def wait_for_ci(
    github,
    sha: str,
    *,
    wait_seconds: float | None = None,
    sleep=asyncio.sleep,
    clock=time.monotonic,
) -> CiVerdict:
    """The verdict on `sha`, waiting while CI runs, at most `wait_seconds`."""
    read = getattr(github, "get_ci_checks", None)
    if read is None or not sha:
        return CiVerdict("none")
    budget = CI_WAIT_SECONDS if wait_seconds is None else wait_seconds
    deadline = clock() + budget
    while True:
        try:
            verdict = ci_verdict(await read(sha))
        except Exception as exc:  # noqa: BLE001 — unreadable CI never blocks a merge
            log.warning("Could not read CI on %s (%s) — merging as before", sha[:7], exc)
            return CiVerdict("none")
        if verdict.state != "pending" or clock() >= deadline:
            return verdict
        await sleep(CI_POLL_SECONDS)


class SharedWait:
    """One CI wait for a whole merge pass, not one per PR.

    Three pending PRs at five minutes each would outrun the review phase's
    budget; the pass waits at most CI_WAIT_SECONDS in all.
    """

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._deadline = clock() + CI_WAIT_SECONDS

    def left(self) -> float:
        return max(0.0, self._deadline - self._clock())


def failing_issues(verdict: CiVerdict) -> list[dict]:
    """The failing checks, shaped like review issues for the Dev's note."""
    return [
        {"severity": "high", "file": c.get("name", ""), "description": c.get("summary") or "failed"}
        for c in verdict.failing
    ]
