"""Developer agent — pick task, implement, test, open PR.

In stub mode (no claude/github clients), logs what it would do.
In real mode, clones the repo, calls claude CLI to implement, pushes a PR.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from datetime import datetime

from langgraph.graph import END, StateGraph

from theswarm.agents.base import load_context, stub_result
from theswarm.config import AgentState, Role

log = logging.getLogger(__name__)


# ── Prompts ─────────────────────────────────────────────────────────────

DEV_SYSTEM = """\
You are a senior developer in an autonomous AI team.

You write clean, production-quality Python code. You follow existing project \
conventions (see AGENT_MEMORY.md). You always write tests for new code.

Rules:
- Follow the project's existing architecture and patterns
- Write unit tests (pytest) alongside implementation
- Keep it simple — prefer the most straightforward solution
- Never commit secrets or hardcoded credentials
- If unsure, pick the simplest approach and document your choice in a code comment
"""

DEV_TASK_PROMPT = """\
## Task

{task_title}

{task_body}

## Project context

{context}

## Instructions

1. Read the existing code to understand the project structure
2. Implement the task described above
3. Write unit tests in tests/unit/ for the new code
4. Make sure the code follows existing conventions (see AGENT_MEMORY.md)
5. Do NOT modify GOLDEN_RULES.md, DOD.md, or AGENT_MEMORY.md
6. After implementation, verify your code compiles/runs correctly

Focus on correctness and simplicity. Ship working code.
"""


# ── Node functions ──────────────────────────────────────────────────────


async def pick_task(state: AgentState) -> dict:
    """Pick the next role:dev + status:ready task from GitHub."""
    github = state.get("github")
    if github is None:
        return stub_result(Role.DEV, "pick_task",
                           "pick first issue with labels role:dev + status:ready")

    # Look for tasks labeled for dev work
    for labels in [["role:dev", "status:ready"], ["status:ready"]]:
        issues = await github.get_issues(labels=labels)
        if issues:
            task = issues[0]
            log.info("Picked task: #%d %s", task["number"], task["title"])
            # Mark as in-progress
            await asyncio.gather(
                github.add_labels(task["number"], ["status:in-progress"]),
                github.remove_label(task["number"], "status:ready"),
            )
            return {"task": task, "tokens_used": 0}

    log.warning("No ready tasks found")
    return {"task": None, "tokens_used": 0}


async def implement_task(state: AgentState) -> dict:
    """Implement the task using Claude CLI in the cloned repo."""
    task = state.get("task")
    if task is None:
        log.info("No task to implement — skipping")
        return {"result": "no task", "tokens_used": 0}

    claude = state.get("claude")
    workspace = state.get("workspace")
    if claude is None or workspace is None:
        return stub_result(Role.DEV, "implement_task",
                           f"would implement #{task['number']}: {task['title']}")

    from theswarm.tools import git as git_ops

    # Create a feature branch
    branch_name = _make_branch_name(task)
    await git_ops.create_branch(workspace, branch_name)

    # Build the prompt
    context = state.get("context", "")
    prompt = DEV_TASK_PROMPT.format(
        task_title=task["title"],
        task_body=task["body"],
        context=context,
    )

    # Run Claude in the workspace
    result = await claude.run(prompt, workdir=workspace)
    log.info("Claude implementation done: %d tokens, $%.4f",
             result.total_tokens, result.cost_usd)

    # Commit all changes
    committed = await git_ops.commit_all(
        workspace,
        f"feat: {task['title']}\n\nCloses #{task['number']}\n\n"
        f"Co-Authored-By: swarm-dev-agent <agent@swarm-bots.local>",
    )

    if not committed:
        log.warning("Claude produced no file changes for task #%d", task["number"])
        return {
            "result": "no changes produced",
            "tokens_used": result.total_tokens,
            "cost_usd": result.cost_usd,
            "branch": branch_name,
        }

    diff_stat = await git_ops.get_diff_stat(workspace)
    log.info("Changes:\n%s", diff_stat)

    return {
        "result": result.text[:500],
        "tokens_used": result.total_tokens,
        "cost_usd": result.cost_usd,
        "branch": branch_name,
        "diff_stat": diff_stat,
    }


async def run_quality_gates(state: AgentState) -> dict:
    """Run tests in the workspace to verify the implementation."""
    task = state.get("task")
    workspace = state.get("workspace")
    claude = state.get("claude")

    if task is None or workspace is None or claude is None:
        return stub_result(Role.DEV, "run_quality_gates",
                           "run pytest on workspace")

    # Run pytest if available
    test_result = await claude.run_tests(
        workspace, "python -m pytest tests/ -v --tb=short", timeout=120,
    )

    if test_result["passed"]:
        log.info("Tests PASSED")
    else:
        log.warning("Tests FAILED:\n%s", test_result["output"][-2000:])

    return {
        "tests_passed": test_result["passed"],
        "test_output": test_result["output"][-2000:],
        "tokens_used": 0,
    }


async def open_pull_request(state: AgentState) -> dict:
    """Push the branch and open a PR on GitHub."""
    task = state.get("task")
    branch = state.get("branch")
    github = state.get("github")
    workspace = state.get("workspace")

    if task is None or branch is None or github is None or workspace is None:
        return stub_result(Role.DEV, "open_pull_request",
                           "git push + create PR")

    from theswarm.tools import git as git_ops

    # Push
    await git_ops.push_branch(workspace, branch)

    # Build PR body
    tests_passed = state.get("tests_passed", False)
    diff_stat = state.get("diff_stat", "")
    test_status = "All tests pass" if tests_passed else "Some tests failing — needs review"

    pr_body = (
        f"## Summary\n\n"
        f"Implements #{task['number']}: {task['title']}\n\n"
        f"## Changes\n\n```\n{diff_stat}\n```\n\n"
        f"## Tests\n\n{test_status}\n\n"
        f"Closes #{task['number']}\n\n"
        f"---\n*Generated by swarm-dev-agent*"
    )

    pr = await github.create_pr(
        branch=branch,
        base="main",
        title=f"[{_extract_us_id(task)}] {task['title']}",
        body=pr_body,
    )

    # Update issue labels
    await github.remove_label(task["number"], "status:in-progress")
    await github.add_labels(task["number"], ["status:review"])

    log.info("Opened PR #%d: %s", pr["number"], pr["url"])
    return {
        "pr": pr,
        "result": f"PR #{pr['number']} opened: {pr['url']}",
        "tokens_used": 0,
    }


# ── Routing ─────────────────────────────────────────────────────────────


def _should_skip(state: AgentState) -> str:
    """Skip remaining nodes if no task was picked."""
    if state.get("task") is None:
        return "end"
    return "implement"


def _should_open_pr(state: AgentState) -> str:
    """Skip PR if no branch was created (no changes)."""
    if state.get("branch") is None:
        return "end"
    return "open_pr"


# ── Graph ───────────────────────────────────────────────────────────────


def build_dev_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("load_context", load_context)
    graph.add_node("pick_task", pick_task)
    graph.add_node("implement", implement_task)
    graph.add_node("quality_gates", run_quality_gates)
    graph.add_node("open_pr", open_pull_request)

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "pick_task")
    graph.add_conditional_edges("pick_task", _should_skip, {
        "implement": "implement",
        "end": END,
    })
    graph.add_edge("implement", "quality_gates")
    graph.add_conditional_edges("quality_gates", _should_open_pr, {
        "open_pr": "open_pr",
        "end": END,
    })
    graph.add_edge("open_pr", END)

    return graph.compile()


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_branch_name(task: dict) -> str:
    """Generate a branch name from a task: feat/us-001-user-registration."""
    title = task["title"].lower()
    # Extract US-XXX if present
    us_match = re.search(r"us-?\d+", title, re.IGNORECASE)
    us_id = us_match.group(0).lower() if us_match else f"issue-{task['number']}"
    # Remove the US-XXX prefix from title before slugifying
    clean_title = re.sub(r"us-?\d+\s*:?\s*", "", title, flags=re.IGNORECASE)
    slug = re.sub(r"[^a-z0-9]+", "-", clean_title)[:40].strip("-")
    return f"feat/{us_id}-{slug}"


def _extract_us_id(task: dict) -> str:
    """Extract 'US-001' from task title, or fallback to issue number."""
    match = re.search(r"US-?\d+", task["title"], re.IGNORECASE)
    return match.group(0) if match else f"#{task['number']}"
