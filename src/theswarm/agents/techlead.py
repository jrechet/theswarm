"""Tech Lead agent — story breakdown + PR review + merge.

In review_loop mode: fetches open PRs, calls Claude for code review,
approves or requests changes, then merges approved PRs.
"""

from __future__ import annotations

import json
import logging

from langgraph.graph import END, StateGraph

from theswarm.agents.base import load_context, stub_result
from theswarm.config import AgentState, Role

log = logging.getLogger(__name__)


# ── Prompts ─────────────────────────────────────────────────────────────

BREAKDOWN_PROMPT = """\
You are the Tech Lead of an autonomous dev team. Break down a user story into \
concrete technical tasks.

## Project context
{context}

## User Story #{issue_number}: {issue_title}

{issue_body}

## Instructions
Break this user story into 2-4 technical tasks. Each task should be:
- Implementable by a single developer in one session
- Specific about which files to create/modify
- Include clear acceptance criteria (what tests must pass)

Return a JSON array:
[
    {{
        "title": "Implement POST /api/v1/resource endpoint",
        "body": "Create the endpoint in src/routers/....\\n\\nAcceptance criteria:\\n- [ ] ...",
        "labels": ["role:dev", "status:ready"]
    }}
]

Rules:
- Tasks should be ordered by dependency (implement models before endpoints)
- Include a test-writing task if the story requires new tests
- Keep task titles in imperative form
- Return ONLY the JSON array, no markdown fences.
"""


REVIEW_SYSTEM = """\
You are the Tech Lead of an autonomous dev team. You review PRs with rigor \
but pragmatism. You focus on correctness, security, and maintainability.

You MUST return valid JSON only. No markdown, no explanation outside the JSON.
"""

REVIEW_PROMPT = """\
Review this Pull Request.

## PR #{pr_number}: {pr_title}

{pr_body}

## Changed files

{files_diff}

## Project context

{context}

## Instructions

Review the code for:
1. **Correctness**: Does it do what the PR/issue says?
2. **Security**: Any OWASP issues (injection, hardcoded secrets, etc.)?
3. **Tests**: Are there tests? Do they cover the main paths?
4. **Conventions**: Does it follow the project conventions in AGENT_MEMORY?
5. **Simplicity**: Any unnecessary complexity?

Return JSON with this exact structure:
{{
    "decision": "APPROVE" or "REQUEST_CHANGES",
    "summary": "1-2 sentence overall assessment",
    "issues": [
        {{
            "severity": "critical" or "major" or "minor" or "nit",
            "file": "path/to/file.py",
            "description": "what's wrong and how to fix it"
        }}
    ]
}}

Rules:
- APPROVE if the code is correct and has no critical/major issues
- REQUEST_CHANGES only for critical or major issues
- Minor issues and nits can be mentioned but should not block approval
- Be pragmatic: this is an MVP, don't demand perfection
"""


# ── Node functions ──────────────────────────────────────────────────────


async def breakdown_stories(state: AgentState) -> dict:
    """Read status:ready issues, call Claude to break them into dev tasks."""
    import re

    github = state.get("github")
    claude = state.get("claude")

    if github is None or claude is None:
        return stub_result(Role.TECHLEAD, "breakdown_stories",
                           "split US into 2-4 technical tasks, create sub-issues")

    # Fetch issues that PO marked as ready but haven't been broken down yet
    ready_issues = await github.get_issues(labels=["status:ready"])
    # Filter out issues that already have sub-tasks (role:dev label)
    ready_issues = [i for i in ready_issues if not any(
        l["name"] == "role:dev" for l in i.get("labels", [])
    )]

    if not ready_issues:
        log.info("TechLead: no issues to break down")
        return {"result": "No issues to break down", "tokens_used": 0}

    context = state.get("context", "")
    total_tokens = 0
    total_cost = 0.0
    tasks_created = 0

    for issue in ready_issues:
        log.info("TechLead: breaking down #%d: %s", issue["number"], issue["title"])

        prompt = BREAKDOWN_PROMPT.format(
            context=context,
            issue_number=issue["number"],
            issue_title=issue["title"],
            issue_body=issue.get("body", "(no description)"),
        )

        result = await claude.run(prompt, timeout=60)
        total_tokens += result.total_tokens
        total_cost += result.cost_usd

        # Parse the task list
        tasks = _parse_tasks_json(result.text)
        if not tasks:
            log.warning("TechLead: could not parse breakdown for #%d", issue["number"])
            continue

        # Create sub-issues for each task
        for task in tasks:
            title = task.get("title", "")
            body = task.get("body", "")
            labels = task.get("labels", ["role:dev", "status:ready"])

            # Reference the parent issue
            body += f"\n\nParent: #{issue['number']}"

            try:
                new_issue = await github.create_issue(
                    title=title,
                    body=body,
                    labels=labels,
                )
                tasks_created += 1
                log.info("TechLead: created task #%d: %s", new_issue["number"], title)
            except Exception as e:
                log.error("TechLead: failed to create task: %s", e)

        # Mark the parent US as broken down (remove status:ready, add status:in-progress)
        try:
            await github.remove_label(issue["number"], "status:ready")
            await github.add_labels(issue["number"], ["status:in-progress"])
        except Exception:
            pass

    log.info("TechLead: created %d tasks from %d user stories", tasks_created, len(ready_issues))

    return {
        "result": f"Broke down {len(ready_issues)} stories into {tasks_created} tasks",
        "tokens_used": total_tokens,
        "cost_usd": total_cost,
    }


async def poll_and_review_prs(state: AgentState) -> dict:
    """Fetch open PRs, review each one with Claude."""
    github = state.get("github")
    claude = state.get("claude")

    if github is None or claude is None:
        return stub_result(Role.TECHLEAD, "poll_and_review_prs",
                           "review open PRs, approve good ones, request changes on others")

    open_prs = await github.get_open_prs()
    if not open_prs:
        log.info("No open PRs to review")
        return {"result": "no open PRs", "tokens_used": 0, "cost_usd": 0.0, "reviews": []}

    log.info("Found %d open PR(s) to review", len(open_prs))
    context = state.get("context", "")
    reviews = []
    total_tokens = 0
    total_cost = 0.0

    for pr in open_prs:
        review = await _review_single_pr(github, claude, pr, context)
        reviews.append(review)
        total_tokens += review.get("tokens_used", 0)
        total_cost += review.get("cost_usd", 0.0)

    return {
        "result": f"Reviewed {len(reviews)} PR(s)",
        "tokens_used": total_tokens,
        "cost_usd": total_cost,
        "reviews": reviews,
    }


async def _review_single_pr(github, claude, pr: dict, context: str) -> dict:
    """Review a single PR: get diff, call Claude, submit review."""
    pr_number = pr["number"]
    log.info("Reviewing PR #%d: %s", pr_number, pr["title"])

    # Get the diff
    files = await github.get_pr_files(pr_number)
    files_diff = _format_files_diff(files)

    # Truncate if too large (keep first 15k chars of diff)
    if len(files_diff) > 15000:
        files_diff = files_diff[:15000] + "\n\n... (diff truncated)"

    prompt = REVIEW_PROMPT.format(
        pr_number=pr_number,
        pr_title=pr["title"],
        pr_body=pr.get("body", ""),
        files_diff=files_diff,
        context=context,
    )

    result = await claude.run(prompt)
    log.info("Claude review done for PR #%d: %d tokens, $%.4f",
             pr_number, result.total_tokens, result.cost_usd)

    # Parse the review
    review_data = _parse_review_json(result.text)
    decision = review_data.get("decision", "COMMENT")
    summary = review_data.get("summary", "Review completed.")
    issues = review_data.get("issues", [])

    # Format the review body
    body = _format_review_body(summary, issues)

    # Submit the review
    event = "APPROVE" if decision == "APPROVE" else "REQUEST_CHANGES"
    review_submitted = False
    try:
        await github.create_pr_review(pr_number, body=body, event=event)
        log.info("PR #%d: %s", pr_number, event)
        review_submitted = True
    except Exception as e:
        # Common case: can't approve own PR (same GitHub token for all agents in MVP)
        log.warning("Could not submit %s review for PR #%d (%s) — posting as comment",
                    event, pr_number, e)
        await github.add_comment(pr_number, f"**Tech Lead Review** ({event})\n\n{body}")
        review_submitted = True  # comment counts as reviewed

    return {
        "pr_number": pr_number,
        "decision": decision,
        "summary": summary,
        "issues": issues,
        "tokens_used": result.total_tokens,
        "cost_usd": result.cost_usd,
    }


async def merge_approved_prs(state: AgentState) -> dict:
    """Merge PRs that were approved in the review step."""
    github = state.get("github")
    reviews = state.get("reviews", [])

    if github is None:
        return stub_result(Role.TECHLEAD, "merge_approved_prs",
                           "merge all approved PRs into main")

    merged = []
    rejected = []
    for review in reviews:
        pr_number = review["pr_number"]
        decision = review.get("decision", "")

        if decision != "APPROVE":
            log.info("PR #%d: skipping merge (decision: %s)", pr_number, decision)
            rejected.append(pr_number)
            continue

        try:
            await github.merge_pr(pr_number, merge_method="squash")
            merged.append(pr_number)
            log.info("Merged PR #%d", pr_number)
        except Exception as e:
            log.error("Failed to merge PR #%d: %s", pr_number, e)

    summary = []
    if merged:
        summary.append(f"Merged: {merged}")
    if rejected:
        summary.append(f"Changes requested: {rejected}")

    return {
        "result": " | ".join(summary) if summary else "No PRs to process",
        "merged_prs": merged,
        "tokens_used": 0,
    }


# ── Routing ─────────────────────────────────────────────────────────────


def _route_phase(state: AgentState) -> str:
    phase = state.get("phase", "breakdown")
    if phase == "review_loop":
        return "poll_and_review_prs"
    return "breakdown_stories"


# ── Graph ───────────────────────────────────────────────────────────────


def build_techlead_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("load_context", load_context)
    graph.add_node("breakdown_stories", breakdown_stories)
    graph.add_node("poll_and_review_prs", poll_and_review_prs)
    graph.add_node("merge_approved_prs", merge_approved_prs)

    graph.set_entry_point("load_context")
    graph.add_conditional_edges("load_context", _route_phase, {
        "breakdown_stories": "breakdown_stories",
        "poll_and_review_prs": "poll_and_review_prs",
    })
    graph.add_edge("breakdown_stories", END)
    graph.add_edge("poll_and_review_prs", "merge_approved_prs")
    graph.add_edge("merge_approved_prs", END)

    return graph.compile()


# ── Helpers ─────────────────────────────────────────────────────────────


def _parse_tasks_json(text: str) -> list[dict]:
    """Parse Claude's task breakdown JSON array."""
    import re

    clean = text.strip()
    # Strip markdown fences
    if clean.startswith("```"):
        clean = re.sub(r"^```\w*\n", "", clean)
        clean = re.sub(r"\n```\s*$", "", clean)

    try:
        result = json.loads(clean)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Try to find a JSON array in the text
    start = clean.find("[")
    end = clean.rfind("]") + 1
    if start >= 0 and end > start:
        try:
            result = json.loads(clean[start:end])
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    log.warning("Could not parse tasks JSON: %s", clean[:200])
    return []


def _format_files_diff(files: list[dict]) -> str:
    """Format PR file diffs for the review prompt."""
    parts = []
    for f in files:
        header = f"### {f['filename']} ({f['status']}, +{f['additions']}/-{f['deletions']})"
        patch = f["patch"]
        if patch:
            parts.append(f"{header}\n```diff\n{patch}\n```")
        else:
            parts.append(f"{header}\n(no diff available)")
    return "\n\n".join(parts)


def _parse_review_json(text: str) -> dict:
    """Parse Claude's review JSON, with fallback."""
    # Strip markdown fences if present
    clean = text.strip()
    if clean.startswith("```"):
        lines = clean.splitlines()
        clean = "\n".join(
            l for l in lines if not l.strip().startswith("```")
        ).strip()

    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        # Try to find JSON in the text
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(clean[start:end])
            except json.JSONDecodeError:
                pass
        log.warning("Could not parse review JSON: %s", clean[:200])
        return {"decision": "COMMENT", "summary": clean[:500], "issues": []}


def _format_review_body(summary: str, issues: list[dict]) -> str:
    """Format a human-readable review body from structured review data."""
    parts = [f"**Summary**: {summary}"]

    if issues:
        parts.append("\n**Issues found:**\n")
        for issue in issues:
            severity = issue.get("severity", "info").upper()
            file = issue.get("file", "")
            desc = issue.get("description", "")
            prefix = {"CRITICAL": "🔴", "MAJOR": "🟠", "MINOR": "🟡", "NIT": "⚪"}.get(
                severity, "ℹ️"
            )
            loc = f" (`{file}`)" if file else ""
            parts.append(f"- {prefix} **{severity}**{loc}: {desc}")
    else:
        parts.append("\nNo issues found. Code looks good.")

    parts.append("\n---\n*Reviewed by swarm-techlead-agent*")
    return "\n".join(parts)
