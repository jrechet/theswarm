"""What a targeted cycle is building: the pinned issue and its breakdown.

Shared by the V1 cycle fragment and the V2 theater. The TechLead breakdown
creates sub-issues carrying ``Parent: #N``; reading them back answers
"the feature was split into X tasks, here is where each one stands".
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PinnedIssue:
    issue: dict | None = None
    children: tuple[dict, ...] = field(default_factory=tuple)
    done: int = 0
    error: str = ""


# Built: in review (a PR is open), or closed as completed — merged, or
# found already on main. A closed sub-task has whatever label it had last,
# often none: lineup-add's #454, closed "already satisfied", read as not
# built and the story "2/3 done" (383c7f77d983, 2026-09-29).
DONE_STATUSES = ("review", "done")


def _child_status(child: dict) -> str:
    """Where a sub-task stands: `done` / `dropped` once closed, else its
    `status:*` label."""
    from theswarm.tools.github import issue_status

    if child.get("state") == "closed":
        return "dropped" if child.get("state_reason") == "not_planned" else "done"
    return issue_status(child)


# The theater polls its stage every 3 s and every render read the pinned
# issue again — every issue of the repository, all states, page after
# page: 600 on concert-tour-app, and a page load took tens of seconds on
# the rate limit's account (V3 M4, 2026-10-07). The answer is kept this
# long per (repository, issue); the suite sets it to 0 (tests/conftest.py).
CACHE_SECONDS_DEFAULT = 20.0
_CACHE: dict[tuple[str, int], tuple[float, PinnedIssue]] = {}


def cache_seconds() -> float:
    try:
        return float(os.environ.get("SWARM_PINNED_CACHE_SECONDS", CACHE_SECONDS_DEFAULT))
    except ValueError:
        return CACHE_SECONDS_DEFAULT


# A read that hangs must not hang the page (2026-10-09: a GitHub ReadTimeout
# retried by PyGithub held a theater's first render for 35 minutes). The
# page waits this long, then draws without the panel; the read goes on, and
# every page that asks meanwhile waits on that one read, never a new one.
READ_TIMEOUT_DEFAULT = 20.0
_INFLIGHT: dict[tuple[str, int], asyncio.Task] = {}


def read_timeout() -> float:
    try:
        return float(os.environ.get("SWARM_PINNED_TIMEOUT_SECONDS", READ_TIMEOUT_DEFAULT))
    except ValueError:
        return READ_TIMEOUT_DEFAULT


def clear_cache() -> None:
    _CACHE.clear()
    _INFLIGHT.clear()


async def load_pinned_issue(repo: str, issue_number: int | None, *, now: float | None = None) -> PinnedIssue:
    if not repo or issue_number is None:
        return PinnedIssue()
    ttl = cache_seconds()
    key = (repo, int(issue_number))
    moment = now if now is not None else time.monotonic()
    if ttl > 0:
        hit = _CACHE.get(key)
        if hit is not None and moment - hit[0] < ttl:
            return hit[1]
    task = _INFLIGHT.get(key)
    if task is None or task.done():
        task = asyncio.ensure_future(_read(repo, int(issue_number), ttl, moment))
        _INFLIGHT[key] = task
        task.add_done_callback(lambda t, k=key: _INFLIGHT.pop(k, None) if _INFLIGHT.get(k) is t else None)
    try:
        return await asyncio.wait_for(asyncio.shield(task), read_timeout())
    except asyncio.TimeoutError:
        log.warning("GitHub did not answer about %s#%s in %.0fs — the page goes on without it", repo, issue_number, read_timeout())
        return PinnedIssue(error=f"GitHub did not answer in {read_timeout():.0f} s")


async def _read(repo: str, issue_number: int, ttl: float, moment: float) -> PinnedIssue:
    key = (repo, issue_number)
    try:
        from theswarm.tools.github import GitHubClient, is_child_of

        client = GitHubClient(repo)
        issue = await client.get_issue(issue_number)
        if issue is None:
            return PinnedIssue()
        # its sub-tasks were opened after it: read back from the newest, stop at it
        everything = await client.get_issues(state="all", created_after=issue_number)
        children = tuple(
            {
                "number": child["number"],
                "title": child["title"],
                "status": _child_status(child),
            }
            for child in everything
            if is_child_of(child.get("body"), issue_number)
        )
        done = sum(1 for c in children if c["status"] in DONE_STATUSES)
        result = PinnedIssue(issue=issue, children=children, done=done)
    except Exception as exc:  # noqa: BLE001 — degrade the panel, not the page
        log.exception("Failed to read issue %s on %s", issue_number, repo)
        return PinnedIssue(error=str(exc)[:200])  # never kept: the next poll tries again
    if ttl > 0:
        _CACHE[key] = (moment, result)
    return result
