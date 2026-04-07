"""Cycle history logger — appends structured cycle results to JSONL.

Each cycle run produces one JSON line in docs/cycle-history.jsonl in the target
repo. This data feeds the dashboard, cost tracking, and future auto-learning.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


async def append_cycle_log(config, result: dict) -> bool:
    """Append a cycle result to the repo's cycle-history.jsonl.

    Returns True on success, False on error.
    """
    if not config.is_real_mode:
        log.info("Cycle log: stub mode, skipping")
        return True

    from theswarm.tools.github import GitHubClient

    github = GitHubClient(config.github_repo)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "date": result.get("date", ""),
        "repo": config.github_repo,
        "tokens": result.get("tokens", 0),
        "cost_usd": round(result.get("cost_usd", 0.0), 4),
        "prs_opened": len(result.get("prs", [])),
        "prs_merged": sum(
            1 for r in result.get("reviews", [])
            if r.get("decision") == "APPROVE"
        ),
        "demo_status": (result.get("demo_report") or {}).get("overall_status", "unknown"),
        "pr_numbers": [p.get("number") for p in result.get("prs", [])],
    }

    line = json.dumps(entry, separators=(",", ":")) + "\n"
    path = "docs/cycle-history.jsonl"

    try:
        # Read existing content
        try:
            existing = await github.get_file_content(path)
        except Exception:
            existing = ""

        updated = existing + line

        await github.update_file(
            path=path,
            content=updated,
            branch="main",
            commit_message=f"chore: cycle log {entry['date']} — ${entry['cost_usd']:.2f}, {entry['prs_opened']} PRs",
        )
        log.info("Cycle log: appended entry for %s", entry["date"])
        return True
    except Exception:
        log.exception("Cycle log: failed to write")
        return False


async def read_cycle_history(github, limit: int = 50) -> list[dict]:
    """Read the most recent cycle history entries.

    Returns a list of dicts, most recent first.
    """
    path = "docs/cycle-history.jsonl"
    try:
        content = await github.get_file_content(path)
    except Exception:
        return []

    entries = []
    for line in content.strip().splitlines():
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    # Most recent first, limited
    return list(reversed(entries[-limit:]))
