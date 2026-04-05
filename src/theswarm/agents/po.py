"""Product Owner agent — daily planning + demo validation + reporting.

Morning: select backlog issues → call Claude to prioritize → label status:ready → write daily plan.
Evening: read QA demo report → validate with Claude → write daily report.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from langgraph.graph import END, StateGraph

from theswarm.agents.base import load_context, stub_result
from theswarm.config import AgentState, Phase, Role

log = logging.getLogger(__name__)

MAX_DAILY_STORIES = 3  # pick at most 3 US per day


# ── Prompts ──────────────────────────────────────────────────────────────

PLAN_PROMPT = """\
You are the Product Owner of an autonomous AI dev team.

## Project context
{context}

## Open backlog issues
{issues}

## Instructions
Select up to {max_stories} user stories from the backlog for today's sprint.
Prioritise by business value and dependency order.

Return a JSON object:
{{
  "selected": [
    {{"number": <issue number>, "title": "<title>", "reason": "<why selected>"}}
  ],
  "daily_plan": "<markdown daily plan (2-4 paragraphs): today's goals, priorities, risks>"
}}

Return ONLY the JSON, no markdown fences.
"""

VALIDATE_PROMPT = """\
You are the Product Owner validating today's demo.

## Project context
{context}

## QA demo report
{demo_report}

## Instructions
Review the demo report. For each quality gate, assess pass/fail.
Write a concise daily report in markdown covering:
1. **User Stories Delivered** — list what was completed
2. **Metrics** — tests passed/failed, issues opened/closed
3. **Quality Assessment** — overall quality verdict (green/yellow/red)
4. **Risks & Blockers** — anything that needs attention
5. **Tomorrow's Focus** — suggested priorities for next cycle

Return the report as plain markdown (no JSON wrapper).
"""


# ── Node functions ──────────────────────────────────────────────────────


async def select_daily_issues(state: AgentState) -> dict:
    """Read backlog, pick 2-3 US for today, label them status:ready."""
    github = state.get("github")
    claude = state.get("claude")

    if github is None or claude is None:
        return stub_result(Role.PO, "select_daily_issues",
                           "select 2-3 issues from backlog, add label status:ready")

    # Fetch backlog issues (status:backlog label)
    backlog = await github.get_issues(labels=["status:backlog"])
    if not backlog:
        # Try unlabelled open issues as fallback
        backlog = await github.get_issues(state="open")
        backlog = [i for i in backlog if not any(
            l["name"].startswith("status:") for l in i.get("labels", [])
        )]

    if not backlog:
        log.info("PO: no backlog issues found — nothing to plan")
        return {
            "daily_plan": "No backlog issues available.",
            "result": "No backlog issues to plan",
            "tokens_used": 0,
        }

    # Format issues for the prompt
    issues_text = "\n".join(
        f"- #{i['number']}: {i['title']}" for i in backlog
    )

    context = state.get("context", "")
    prompt = PLAN_PROMPT.format(
        context=context,
        issues=issues_text,
        max_stories=MAX_DAILY_STORIES,
    )

    result = await claude.run(prompt, workdir=state.get("workspace"), timeout=60)

    # Parse Claude's response
    selected = []
    daily_plan = ""
    try:
        data = json.loads(result.text)
        selected = data.get("selected", [])
        daily_plan = data.get("daily_plan", "")
    except (json.JSONDecodeError, TypeError):
        # If Claude didn't return valid JSON, use text as the plan
        log.warning("PO: could not parse planning JSON, using raw text")
        daily_plan = result.text

    # Label selected issues as status:ready
    for item in selected:
        issue_num = item.get("number")
        if issue_num:
            try:
                await github.remove_label(issue_num, "status:backlog")
            except Exception:
                pass
            try:
                await github.add_labels(issue_num, ["status:ready"])
            except Exception:
                log.warning("PO: could not label issue #%s", issue_num)

    selected_nums = [s.get("number") for s in selected]
    log.info("PO selected %d issues for today: %s", len(selected), selected_nums)

    return {
        "daily_plan": daily_plan,
        "tokens_used": result.total_tokens,
        "cost_usd": result.cost_usd,
    }


async def write_daily_plan(state: AgentState) -> dict:
    """Write docs/daily-plans/YYYY-MM-DD.md to the repo."""
    github = state.get("github")
    daily_plan = state.get("daily_plan", "")

    if not daily_plan or github is None:
        return stub_result(Role.PO, "write_daily_plan",
                           "create daily plan markdown in docs/daily-plans/")

    today = datetime.now().strftime("%Y-%m-%d")
    path = f"docs/daily-plans/{today}.md"
    content = f"# Daily Plan — {today}\n\n{daily_plan}\n"

    try:
        await github.update_file(
            path=path,
            content=content,
            commit_message=f"PO: daily plan for {today}",
            branch="main",
        )
        log.info("PO: wrote daily plan to %s", path)
    except Exception as exc:
        log.warning("PO: could not write daily plan file: %s", exc)

    return {
        "result": f"Daily plan written to {path}",
        "tokens_used": 0,
    }


async def validate_demo(state: AgentState) -> dict:
    """Read QA demo report and validate against acceptance criteria."""
    claude = state.get("claude")
    demo_report = state.get("demo_report")

    if claude is None:
        return stub_result(Role.PO, "validate_demo",
                           "read report.json, check each US against acceptance criteria")

    # Format demo report for the prompt
    if demo_report:
        report_text = json.dumps(demo_report, indent=2)
    else:
        report_text = "(No demo report available — QA may not have run)"

    context = state.get("context", "")
    prompt = VALIDATE_PROMPT.format(
        context=context,
        demo_report=report_text,
    )

    result = await claude.run(prompt, workdir=state.get("workspace"), timeout=60)

    return {
        "daily_report": result.text,
        "tokens_used": result.total_tokens,
        "cost_usd": result.cost_usd,
    }


async def write_daily_report(state: AgentState) -> dict:
    """Write the end-of-day report to the repo."""
    github = state.get("github")
    daily_report = state.get("daily_report", "")

    if not daily_report or github is None:
        return stub_result(Role.PO, "write_daily_report",
                           "write daily report summarising US delivered, metrics, risks")

    today = datetime.now().strftime("%Y-%m-%d")
    path = f"docs/daily-reports/{today}.md"
    content = f"# Daily Report — {today}\n\n{daily_report}\n"

    try:
        await github.update_file(
            path=path,
            content=content,
            commit_message=f"PO: daily report for {today}",
            branch="main",
        )
        log.info("PO: wrote daily report to %s", path)
    except Exception as exc:
        log.warning("PO: could not write daily report file: %s", exc)

    # Print report to console for visibility
    print(f"\n{'─' * 40}")
    print(f"DAILY REPORT — {today}")
    print(f"{'─' * 40}")
    print(daily_report[:2000])
    print(f"{'─' * 40}\n")

    return {
        "result": f"Daily report written to {path}",
        "tokens_used": 0,
    }


def _route_phase(state: AgentState) -> str:
    phase = state.get("phase", Phase.MORNING.value)
    if phase == Phase.EVENING.value:
        return "validate_demo"
    return "select_daily_issues"


# ── Graph ───────────────────────────────────────────────────────────────


def build_po_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("load_context", load_context)
    graph.add_node("select_daily_issues", select_daily_issues)
    graph.add_node("write_daily_plan", write_daily_plan)
    graph.add_node("validate_demo", validate_demo)
    graph.add_node("write_daily_report", write_daily_report)

    graph.set_entry_point("load_context")
    graph.add_conditional_edges("load_context", _route_phase, {
        "select_daily_issues": "select_daily_issues",
        "validate_demo": "validate_demo",
    })
    # Morning path
    graph.add_edge("select_daily_issues", "write_daily_plan")
    graph.add_edge("write_daily_plan", END)
    # Evening path
    graph.add_edge("validate_demo", "write_daily_report")
    graph.add_edge("write_daily_report", END)

    return graph.compile()
