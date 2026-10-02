"""The demo is announced on the issue that asked for it.

A feature asked for on GitHub — the `swarm:go` label, or an issue the
owner pressed Play on and walked away from — got its PRs, its merges and
its demo, and the issue said nothing: the demo sat on a page nobody was
told about. When a cycle's demo is ready (`DemoReady`, after the report
is stored) the swarm comments on the pinned issue with the player's link
and what was built — once per cycle (a marker in the comment), only when
the server knows its public URL (a relative link is useless on GitHub),
and never at the cost of anything else: a failure is logged.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

log = logging.getLogger(__name__)

_MARKER = "<!-- swarm:demo {cycle_id} -->"


def demo_comment(report: Any, play_url: str) -> str:
    """The comment: the link first, then what was built and how QA judged it."""
    summary = report.summary
    facts = [f"{summary.prs_merged} PR{'s' if summary.prs_merged != 1 else ''} merged"]
    if summary.prs_held:
        facts.append(f"{summary.prs_held} held for review")
    if summary.stories_total:
        facts.append(f"{summary.stories_completed}/{summary.stories_total} stories")
    if summary.tests_total:
        facts.append(f"{summary.tests_passing}/{summary.tests_total} tests")
    if summary.coverage_percent:
        facts.append(f"{summary.coverage_percent:.1f}% coverage")
    gates = [
        f"{gate.name.replace('_', ' ')}: {gate.status.value}"
        for gate in report.quality_gates
        if gate.name in ("feature_pages", "feature_calls", "e2e_tests")
    ]
    lines = [
        f"🎬 **The demo is ready** — [watch it]({play_url})",
        "",
        " · ".join(facts),
    ]
    if gates:
        lines += ["", "On the running app: " + " · ".join(gates)]
    lines += ["", _MARKER.format(cycle_id=report.cycle_id)]
    return "\n".join(lines)


async def announce_demo(
    event: Any,
    *,
    external_url: str,
    report_repo: Any,
    github_for: Callable[[str], Any],
) -> bool:
    """Comment on the cycle's issue; True when a comment was posted."""
    issue = getattr(event, "issue_number", None)
    if not issue or not external_url or report_repo is None:
        return False
    try:
        report = await report_repo.get(event.report_id)
        if report is None:
            return False
        github = github_for(event.project_id)
        marker = _MARKER.format(cycle_id=event.cycle_id)
        comments = await github.get_issue_comments(issue)
        if any(marker in str(c.get("body", "")) for c in comments or ()):
            return False
        play_url = f"{external_url.rstrip('/')}/demos/{event.report_id}/play"
        await github.add_comment(issue, demo_comment(report, play_url))
    except Exception:  # noqa: BLE001 — an announcement is a courtesy
        log.warning("announcing the demo of %s on %s#%s failed",
                    event.cycle_id, event.project_id, issue, exc_info=True)
        return False
    log.info("Demo of %s announced on %s#%s", event.cycle_id, event.project_id, issue)
    return True
