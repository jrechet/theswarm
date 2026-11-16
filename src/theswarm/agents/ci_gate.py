"""Read a pull request's CI before merging it.

The TechLead merged every APPROVE without looking, and branch protection
does not stop it: TheSwarm's main exempts the admin token the swarm merges
with. (concert-tour-app has no CI at all: there the gate reads "none" and
the merge goes ahead as before.) A red PR goes back to the Dev; a PR whose CI is still
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
# A head GitHub just made (main merged in) has no checks for a few seconds.
CI_REGISTER_SECONDS = 60
CI_REGISTER_POLL_SECONDS = 5

# On the task issue, next to CHANGES_MARKER: why the PR came back.
CI_RED_MARKER = "<!-- swarm:ci-red -->"
CI_RED_ON_HEAD = "CI red — back to the Dev"
CI_RED_SUMMARY = (
    "This PR was approved but its CI is red, so it was not merged. Read "
    "what the failing checks below report, reproduce it locally, fix it on "
    "this branch and push; do not start over."
)

_OWN_CONTEXTS = frozenset({"theswarm/review"})
# Every status the swarm writes on a head is its own word, never CI: the
# review's, and each free persona's (`theswarm/extra-<key>`, B3) — a persona's
# "failure" read as red CI would send the PR back a second time, as a bug.
_OWN_PREFIX = "theswarm/"
_RED = frozenset({"failure", "error", "timed_out", "action_required", "startup_failure"})
_PENDING = frozenset({"pending", "queued", "in_progress", "waiting", "requested", "expected"})
_NO_SIGNAL = frozenset({"cancelled", "skipped", "neutral", "stale"})
# A red that is the pipeline's, not the code's (DevOps D2): the job never
# started, the runner or the slot, the deploy. Such a PR waits for the next
# pass instead of going back to the Dev with a note that would send it
# hunting for a bug that does not exist.
_INFRA_STATES = frozenset({"startup_failure", "action_required"})
_INFRA_WORDS = ("runner", "set up job", "deploy", "infra", "self-hosted", "slot", "lost communication",
                "no space left", "docker", "registry")


@dataclass(frozen=True)
class CiVerdict:
    """green | red | pending | none, and the checks that failed."""

    state: str
    failing: tuple[dict, ...] = field(default_factory=tuple)


def ci_verdict(checks: list[dict]) -> CiVerdict:
    """What CI says about one commit, from its flattened statuses and check runs."""
    signals = [
        c for c in checks
        if c.get("name") not in _OWN_CONTEXTS and not str(c.get("name") or "").startswith(_OWN_PREFIX)
        and c.get("state") not in _NO_SIGNAL
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
    new_head: bool = False,
) -> CiVerdict:
    """The verdict on `sha`, waiting while CI runs, at most `wait_seconds`.

    `new_head`: the commit was made a moment ago (main merged in, A1 bis
    C3), and its checks may not be registered yet — no signal is waited for
    `CI_REGISTER_SECONDS` before it is read as "no CI"."""
    read = getattr(github, "get_ci_checks", None)
    if read is None or not sha:
        return CiVerdict("none")
    budget = CI_WAIT_SECONDS if wait_seconds is None else wait_seconds
    started = clock()
    deadline = started + budget
    while True:
        try:
            verdict = ci_verdict(await read(sha))
        except Exception as exc:  # noqa: BLE001 — unreadable CI never blocks a merge
            log.warning("Could not read CI on %s (%s) — merging as before", sha[:7], exc)
            return CiVerdict("none")
        registering = new_head and verdict.state == "none" and clock() < started + CI_REGISTER_SECONDS
        if clock() >= deadline:
            return CiVerdict("pending") if registering else verdict  # never merged unread
        if verdict.state != "pending" and not registering:
            return verdict
        await sleep(CI_REGISTER_POLL_SECONDS if registering else CI_POLL_SECONDS)


class SharedWait:
    """One CI wait for a whole merge pass, not one per PR.

    Three pending PRs at five minutes each would outrun the review phase's
    budget; the pass waits at most CI_WAIT_SECONDS in all.
    """

    def __init__(self, clock=time.monotonic, *, seconds: float | None = None) -> None:
        self._clock = clock
        self._deadline = clock() + (CI_WAIT_SECONDS if seconds is None else seconds)

    def left(self) -> float:
        return max(0.0, self._deadline - self._clock())


def triage(verdict: CiVerdict) -> str:
    """"code" or "infra": every failing check must read as the pipeline's for
    the red to be infra — one failing test job makes it the code's."""
    if verdict.state != "red" or not verdict.failing:
        return "code"
    for check in verdict.failing:
        words = f"{check.get('name', '')} {check.get('summary', '')}".lower()
        if check.get("state") in _INFRA_STATES or any(w in words for w in _INFRA_WORDS):
            continue
        return "code"
    return "infra"


def failing_issues(verdict: CiVerdict) -> list[dict]:
    """The failing checks, shaped like review issues for the Dev's note."""
    return [
        {"severity": "high", "file": c.get("name", ""), "description": c.get("summary") or "failed"}
        for c in verdict.failing
    ]
