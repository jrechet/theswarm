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


async def load_pinned_issue(repo: str, issue_number: int | None) -> PinnedIssue:
    if not repo or issue_number is None:
        return PinnedIssue()
    try:
        from theswarm.tools.github import GitHubClient, issue_status

        client = GitHubClient(repo)
        issue = await client.get_issue(issue_number)
        if issue is None:
            return PinnedIssue()
        marker = f"Parent: #{issue_number}"
        everything = await client.get_issues(state="all")
        children = tuple(
            {
                "number": child["number"],
                "title": child["title"],
                "status": issue_status(child),
            }
            for child in everything
            if marker in (child.get("body") or "")
        )
        done = sum(1 for c in children if c["status"] == "review")
        return PinnedIssue(issue=issue, children=children, done=done)
    except Exception as exc:  # noqa: BLE001 — degrade the panel, not the page
        log.exception("Failed to read issue %s on %s", issue_number, repo)
        return PinnedIssue(error=str(exc)[:200])
