"""What a targeted cycle is building: the pinned issue and its breakdown.

Shared by the V1 cycle fragment and the V2 theater. The TechLead breakdown
creates sub-issues carrying ``Parent: #N``; reading them back answers
"the feature was split into X tasks, here is where each one stands".
"""

from __future__ import annotations

import logging
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


async def load_pinned_issue(repo: str, issue_number: int | None) -> PinnedIssue:
    if not repo or issue_number is None:
        return PinnedIssue()
    try:
        from theswarm.tools.github import GitHubClient, is_child_of

        client = GitHubClient(repo)
        issue = await client.get_issue(issue_number)
        if issue is None:
            return PinnedIssue()
        everything = await client.get_issues(state="all")
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
        return PinnedIssue(issue=issue, children=children, done=done)
    except Exception as exc:  # noqa: BLE001 — degrade the panel, not the page
        log.exception("Failed to read issue %s on %s", issue_number, repo)
        return PinnedIssue(error=str(exc)[:200])
