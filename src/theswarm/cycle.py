"""Orchestrate one full daily cycle: morning → dev → demo → report."""

from __future__ import annotations

import asyncio
import os
import logging
from datetime import datetime

from theswarm.agents.dev import build_dev_graph
from theswarm.agents.po import build_po_graph
from theswarm.agents.qa import build_qa_graph
from theswarm.agents.techlead import build_techlead_graph
from theswarm.config import CycleConfig, Phase, Role
from theswarm.cycle_budgets import (  # noqa: F401 — re-exported for callers and tests
    MAX_DEV_ITERATIONS,
    PHASE_TIMEOUTS,
    BudgetExceeded,
    PhaseTimeout,
)
from theswarm.domain.cycles.value_objects import PHASE_ROLE
from theswarm.infrastructure import tracing
from theswarm.token_counter import TokenTracker
from theswarm.tools.claude import ClaudeFatalError

log = logging.getLogger(__name__)

MAX_AUTONOMOUS_CYCLES = 10  # safety cap for autonomous mode
MAX_DAILY_STORIES = 3  # imported by PO but defined here for reference

# One cycle per repository at a time, whatever started it — the API, the
# Mattermost gateway, the autonomous loop or the resumer after a deploy.
# The workspace is one directory per repo, and a cycle treats it as its own:
# `git reset --hard`, `clean -fd`, `checkout -B`, and rm -rf at the end.
_repo_locks: dict[str, tuple[asyncio.AbstractEventLoop, asyncio.Lock]] = {}


# How many cycles may run at once, all repositories together (V2, M5).
# One per repo is a correctness rule (the workspace); this one is about
# the box: a 2 GB container and one shared subscription window.
DEFAULT_MAX_CONCURRENT_CYCLES = 1
_cycle_slots: dict[str, tuple[asyncio.AbstractEventLoop, int, asyncio.Semaphore]] = {}


def max_concurrent_cycles() -> int:
    raw = os.environ.get("SWARM_MAX_CONCURRENT_CYCLES", "").strip()
    try:
        return max(1, int(raw)) if raw else DEFAULT_MAX_CONCURRENT_CYCLES
    except ValueError:
        return DEFAULT_MAX_CONCURRENT_CYCLES


def cycle_slot() -> asyncio.Semaphore:
    """The semaphore every cycle holds while it runs, sized by
    SWARM_MAX_CONCURRENT_CYCLES. Per loop, like `repo_lock`; rebuilt when
    the configured size changes."""
    loop = asyncio.get_running_loop()
    size = max_concurrent_cycles()
    entry = _cycle_slots.get("global")
    if entry is None or entry[0] is not loop or entry[1] != size:
        entry = _cycle_slots["global"] = (loop, size, asyncio.Semaphore(size))
    return entry[2]


def repo_lock(repo: str) -> asyncio.Lock:
    """The lock every cycle on `repo` must hold while it runs.

    Call it from a coroutine. An asyncio.Lock binds to the loop that first
    waits on it, so a lock left over from a loop that no longer runs is
    replaced rather than reused — nothing on a dead loop can be holding it.
    """
    loop = asyncio.get_running_loop()
    entry = _repo_locks.get(repo)
    if entry is None or entry[0] is not loop:
        entry = _repo_locks[repo] = (loop, asyncio.Lock())
    return entry[1]


# Per-phase hard timeouts (seconds). Beyond this we abort the phase rather
# than letting it hang indefinitely.
#


async def _merge_held_prs(github, held: list[int], on_progress) -> list[int]:
    """Merge the approved PRs the review phase held back. Returns those merged.

    A merge that fails leaves its PR open and its branch alone. Cycle 6 is
    why: #164 and #165 rewrote the same file, and merging one made the other
    unmergeable — reporting it as merged would have hidden work that never
    landed.
    """
    if github is None or not held:
        return []

    merged: list[int] = []
    try:
        open_prs = await github.get_open_prs()
    except Exception:
        open_prs = []
    branches = {p["number"]: p.get("head") for p in open_prs}

    shas = {p["number"]: p.get("head_sha", "") for p in open_prs}
    by_number = {p["number"]: p for p in open_prs}
    merged_tasks: list[int] = []
    from theswarm.agents import ci_gate
    from theswarm.agents.techlead import _task_of_pr, close_finished_stories

    ci_wait = ci_gate.SharedWait()
    for pr_number in held:
        # Main's protection exempts the admin token the swarm merges with:
        # nothing but this stops a red PR landing on main.
        verdict = await ci_gate.wait_for_ci(
            github, shas.get(pr_number, ""), wait_seconds=ci_wait.left(),
        )
        if verdict.state in ("red", "pending"):
            log.warning("PR #%d was approved but its CI is %s — left open", pr_number, verdict.state)
            continue
        try:
            await github.merge_pr(pr_number, merge_method="squash")
        except Exception as exc:
            log.warning(
                "PR #%d was approved but did not merge (%s) — left open",
                pr_number, exc,
            )
            continue
        merged.append(pr_number)
        log.info("Merged approved PR #%d at end of cycle", pr_number)
        task = _task_of_pr({"number": pr_number, **by_number.get(pr_number, {})})
        if task is not None:
            merged_tasks.append(task)
        branch = branches.get(pr_number)
        if branch:
            try:
                await github.delete_branch(branch)
            except Exception:
                log.warning("Could not delete branch %s after merge", branch)

    closed_stories = await close_finished_stories(github, merged_tasks)
    if on_progress is not None and merged:
        try:
            await on_progress("TechLead", f"Merged approved PRs {merged}")
            if closed_stories:
                await on_progress("TechLead", f"Stories done: {closed_stories}")
        except Exception:
            pass
    return merged


async def _write_cycle_learnings(
    base_state: dict,
    cycle_result: dict,
    _progress,
) -> None:
    """Run retrospective and update structured agent memory after a cycle.

    Uses Claude to analyze the cycle and extract actionable learnings,
    then appends them to AGENT_MEMORY.jsonl. Triggers compaction if
    memory exceeds 50 entries.
    """
    from theswarm.memory_store import (
        append_entries, load_entries, make_entry,
        run_retrospective, compact_memory,
    )

    github = base_state.get("github")
    claude = base_state.get("claude")
    if not github:
        return

    await _progress("Memory", "Running retrospective…")

    # Collect basic facts (always, even without Claude)
    fact_entries = []
    demo = cycle_result.get("demo_report", {})
    security = demo.get("quality_gates", {}).get("security", {}) if demo else {}
    coverage_gate = demo.get("quality_gates", {}).get("coverage", {}) if demo else {}

    if coverage_gate.get("percent"):
        fact_entries.append(make_entry(
            category="stack",
            content=f"Code coverage: {coverage_gate['percent']}%",
            agent="QA",
            cycle_date=cycle_result.get("date", ""),
        ))

    if security.get("semgrep_high", 0) > 0:
        fact_entries.append(make_entry(
            category="errors",
            content=f"Semgrep found {security['semgrep_high']} high-severity findings",
            agent="QA",
            cycle_date=cycle_result.get("date", ""),
        ))

    # Run Claude-powered retrospective if available
    retro_entries = []
    if claude:
        try:
            retro_entries = await run_retrospective(github, claude, cycle_result)
        except Exception:
            log.exception("Retrospective failed")

    # Run auto-learning from feedback signals (M6)
    feedback_entries = []
    if claude:
        try:
            from theswarm.feedback import process_cycle_feedback
            feedback_entries = await process_cycle_feedback(github, claude, cycle_result)
            if feedback_entries:
                await _progress("Memory", f"Extracted {len(feedback_entries)} lessons from feedback")
        except Exception:
            log.exception("Feedback processing failed")

    all_new = fact_entries + retro_entries + feedback_entries
    if all_new:
        await append_entries(github, all_new)
        await _progress("Memory", f"Added {len(all_new)} memory entries ({len(retro_entries)} retro, {len(feedback_entries)} feedback)")

    # Compact if memory is getting large
    if claude:
        try:
            compacted = await compact_memory(github, claude, threshold=50)
            if compacted:
                await _progress("Memory", "Memory compacted")
        except Exception:
            log.exception("Memory compaction failed")


def _build_base_state(config: CycleConfig) -> dict:
    """Build the base state dict, wiring real clients if in real mode."""
    state: dict = {
        "team_id": config.team_id,
        "github_repo": config.github_repo,
        "project_id": config.project_id or config.team_id,
        "codenames": dict(config.codenames or {}),
        "github": None,
        "claude": None,
        "workspace": None,
        # Honour the project's configured retry budget instead of the
        # dev-graph default.
        "max_dev_retries": config.max_dev_retries,
        "target_issue": config.target_issue,
    }

    if config.is_real_mode:
        from theswarm.tools.claude import ClaudeCLI
        from theswarm.tools.github import GitHubClient

        state["github"] = GitHubClient(config.github_repo)
        state["claude"] = ClaudeCLI(model=config.claude_model)
        state["workspace"] = config.workspace_dir

    return state


async def _ensure_workspace(config: CycleConfig) -> None:
    """Clone or pull the target repo into the workspace dir."""
    if not config.is_real_mode:
        return

    from theswarm.tools.git import clone_repo
    await clone_repo(config.repo_clone_url, config.workspace_dir)


async def _requeue_unfinished(config) -> list[int]:
    """Return this cycle's claimed-but-unfinished tasks to the ready queue.

    A task the Dev started carries status:in-progress. If the loop ends
    before finishing it, that label survives and misrepresents the work as
    under way. Putting it back to status:ready is both honest and what lets
    the next cycle pick it up from a clean state.

    Scoped to the pinned issue's children: an untargeted cycle has no claim
    over what other cycles may be holding.
    """
    target = getattr(config, "target_issue", None)
    if not target:
        return []
    from theswarm.tools.github import GitHubClient, is_child_of

    try:
        github = GitHubClient(config.github_repo)
        children = await github.get_issues(labels=["role:dev", "status:in-progress"])
        requeued: list[int] = []
        for child in children:
            if not is_child_of(child.get("body"), target):
                continue
            number = child["number"]
            await github.add_labels(number, ["status:ready"])
            await github.remove_label(number, "status:in-progress")
            requeued.append(number)
            log.info("Handed back task #%d — claimed but not finished", number)
        return requeued
    except Exception:  # noqa: BLE001 — tidying must never fail the cycle
        log.exception("Could not hand back unfinished tasks")
        return []


async def _pull_latest(config: CycleConfig) -> None:
    """Pull latest main into the workspace (after a merge)."""
    if not config.is_real_mode:
        return

    from theswarm.tools.git import _auth_args, _run_git
    await _run_git("checkout", "main", cwd=config.workspace_dir, check=False)
    await _run_git(
        *_auth_args(), "pull", "--ff-only", cwd=config.workspace_dir, check=False,
    )


async def run_daily_cycle(
    config: CycleConfig,
    on_progress=None,
    on_checkpoint=None,
    resume_from: str | None = None,
    *,
    cycle_id: str | None = None,
    checkpointer=None,
    resume: bool = False,
) -> dict:
    """Run one complete daily cycle and return the summary.

    Since V2 M4 the cycle is a durable LangGraph (`cycle_graph.py`): every
    phase is a node, checkpointed on ``checkpointer`` under ``cycle_id`` as
    the thread id. ``resume=True`` continues an interrupted cycle from the
    node after the last one that finished — the same ``cycle_id``, the same
    checkpointer, a fresh workspace.

    Args:
        config: Cycle configuration.
        on_progress: Optional async callback ``(role, message) -> None`` for live updates.
        on_checkpoint: Optional async callback ``(phase: str, ok: bool, state: dict) -> None``
            called after each phase completes or fails. Sprint G1; kept for the
            V1 cycles page until M7.
        resume_from: Legacy phase name from the pre-M4 resumer; any value means
            ``resume=True`` (the graph knows where it stopped).
        cycle_id: The thread the graph checkpoints under (a fresh id by default).
        checkpointer: A LangGraph checkpointer; in memory when None (no durability).
        resume: Continue the thread instead of starting a cycle.
    """
    import uuid

    from theswarm.application.services.watchdog import AgentWatchdog
    from theswarm.cycle_graph import CycleRuntime, run_cycle_graph

    today = datetime.now().strftime("%Y-%m-%d")
    resume = resume or bool(resume_from)
    cycle_id = cycle_id or uuid.uuid4().hex[:12]

    watchdog = AgentWatchdog(
        idle_threshold=config.watchdog_idle_threshold,
        max_warnings=config.watchdog_max_warnings,
    )
    await watchdog.start()

    async def _progress(role: str, message: str) -> None:
        watchdog.heartbeat(role, message)
        log.info("[%s] %s", role, message)
        print(f"[{role}] {message}")
        if on_progress:
            try:
                await on_progress(role, message)
            except Exception:
                pass

    async def _checkpoint(phase: str, ok: bool, snapshot: dict) -> None:
        if on_checkpoint is None:
            return
        try:
            await on_checkpoint(phase, ok, snapshot)
        except Exception:
            log.exception("on_checkpoint raised (continuing)")

    print(f"\n{'=' * 60}")
    print(f"SWARM CYCLE — {today}{' (resumed)' if resume else ''}")
    print(f"{'=' * 60}\n")

    # Prepare workspace — on a resume too: the container that died took
    # its clone with it.
    await _ensure_workspace(config)
    base_state = _build_base_state(config)

    runtime = CycleRuntime(
        config=config,
        base_state=base_state,
        progress=_progress,
        raw_progress=on_progress,
        checkpoint=_checkpoint,
        watchdog=watchdog,
    )

    # V2 runtime (M1): the SDK backend streams every tool call and text
    # block; they reach the theater — and the watchdog, as heartbeats — as
    # progress of the role whose phase is running.
    _claude = base_state.get("claude")
    if _claude is not None and hasattr(_claude, "on_event"):
        async def _on_claude_event(message: str) -> None:
            await _progress(runtime.current_role["name"], message)

        _claude.on_event = _on_claude_event

    try:
        return await run_cycle_graph(
            runtime, cycle_id=cycle_id, checkpointer=checkpointer,
            resume=resume, date=today,
        )
    except Exception as exc:
        # Sprint G1 — persist a failed checkpoint for the phase that crashed
        # so /cycles/{id}/resume can pick up from the next one.
        failed_phase = runtime.current_phase["name"]
        await _checkpoint(
            failed_phase, False,
            {"error": f"{type(exc).__name__}: {exc}"},
        )
        raise
    finally:
        await watchdog.stop()
        if runtime.dev_claims_open:
            # Cancelled or crashed mid-loop: give back what was claimed.
            # _requeue_unfinished never raises; a hand-back that fails is
            # logged, not fatal, and the next cycle's picker copes.
            await _requeue_unfinished(config)
        # Cleanup workspace even on failure
        if config.is_real_mode:
            from theswarm.tools.git import cleanup_workspace
            await cleanup_workspace(config.workspace_dir)


async def run_dev_only(config: CycleConfig) -> dict:
    """Run only the Dev agent — useful for testing a single task."""
    today = datetime.now().strftime("%Y-%m-%d")
    tracker = TokenTracker()

    print(f"\n{'=' * 60}")
    print(f"SWARM DEV AGENT — {today}")
    print(f"{'=' * 60}\n")

    await _ensure_workspace(config)
    base_state = _build_base_state(config)

    dev = build_dev_graph()
    dev_state = await dev.ainvoke({**base_state, "phase": Phase.DEVELOPMENT.value})
    dev_tokens = dev_state.get("tokens_used", 0)
    dev_cost = dev_state.get("cost_usd", 0.0)
    tracker.record("dev", dev_tokens, dev_cost)

    print(f"\n{'=' * 60}")
    print("DEV AGENT DONE")
    print(f"{'=' * 60}")
    tracker.print_summary()

    pr = dev_state.get("pr")
    if pr:
        print(f"\nPR: {pr['url']}")

    return {
        "date": today,
        "tokens": dev_tokens,
        "cost_usd": dev_cost,
        "pr": pr,
    }


async def run_techlead_only(config: CycleConfig) -> dict:
    """Run only the TechLead in review mode — reviews and merges open PRs."""
    today = datetime.now().strftime("%Y-%m-%d")
    tracker = TokenTracker()

    print(f"\n{'=' * 60}")
    print(f"SWARM TECHLEAD AGENT — {today}")
    print(f"{'=' * 60}\n")

    await _ensure_workspace(config)
    base_state = _build_base_state(config)

    tl = build_techlead_graph()
    tl_state = await tl.ainvoke({**base_state, "phase": "review_loop"})
    tl_tokens = tl_state.get("tokens_used", 0)
    tl_cost = tl_state.get("cost_usd", 0.0)
    tracker.record("techlead", tl_tokens, tl_cost)

    print(f"\n{'=' * 60}")
    print("TECHLEAD AGENT DONE")
    print(f"{'=' * 60}")
    tracker.print_summary()

    reviews = tl_state.get("reviews", [])
    for r in reviews:
        print(f"  PR #{r['pr_number']}: {r['decision']} — {r.get('summary', '')[:80]}")

    return {
        "date": today,
        "tokens": tl_tokens,
        "cost_usd": tl_cost,
        "reviews": reviews,
    }


async def _check_project_done(config: CycleConfig) -> tuple[bool, str]:
    """Check if a project has no remaining work (all stories resolved).

    Returns (is_done, reason_string).
    """
    if not config.is_real_mode:
        return True, "Stub mode — nothing to do"

    from theswarm.tools.github import GitHubClient

    github = GitHubClient(config.github_repo)

    # Check for open issues with work-related labels
    open_issues = await github.get_issues(state="open")
    work_issues = [
        i for i in open_issues
        if not any(lbl in ("wontfix", "duplicate", "invalid")
                   for lbl in (i.get("labels") or []))
    ]

    # Check for open PRs
    open_prs = await github.get_open_prs()

    if not work_issues and not open_prs:
        return True, "All issues closed, no open PRs"

    backlog = [i for i in work_issues
               if any(lbl in ("status:backlog",) for lbl in (i.get("labels") or []))]
    ready = [i for i in work_issues
             if any(lbl in ("status:ready",) for lbl in (i.get("labels") or []))]
    in_progress = [i for i in work_issues
                   if any(lbl in ("status:in-progress",) for lbl in (i.get("labels") or []))]
    unlabeled = [i for i in work_issues
                 if not any(lbl.startswith("status:") for lbl in (i.get("labels") or []))]

    summary = (
        f"backlog={len(backlog)} ready={len(ready)} "
        f"in_progress={len(in_progress)} unlabeled={len(unlabeled)} "
        f"open_prs={len(open_prs)}"
    )

    return False, summary


async def run_autonomous(
    config: CycleConfig,
    max_cycles: int = MAX_AUTONOMOUS_CYCLES,
    on_progress=None,
) -> dict:
    """Run cycles in a loop until all user stories are resolved or max_cycles hit.

    Returns a summary dict with all cycle results.
    """
    total_cost = 0.0
    total_tokens = 0
    cycle_results: list[dict] = []

    print(f"\n{'=' * 60}")
    print(f"AUTONOMOUS MODE — repo: {config.github_repo}")
    print(f"Max cycles: {max_cycles}")
    print(f"{'=' * 60}\n")

    for cycle_num in range(1, max_cycles + 1):
        print(f"\n{'─' * 60}")
        print(f"AUTONOMOUS CYCLE {cycle_num}/{max_cycles}")
        print(f"{'─' * 60}\n")

        # Check if we're done before starting a new cycle
        if cycle_num > 1:
            is_done, status = await _check_project_done(config)
            if is_done:
                print(f"\nPROJECT COMPLETE: {status}")
                break
            print(f"Remaining work: {status}")

        try:
            async with repo_lock(config.github_repo):
                result = await run_daily_cycle(config, on_progress=on_progress)
            cycle_results.append(result)
            total_cost += result.get("cost_usd", 0.0)
            total_tokens += result.get("tokens", 0)

            demo = result.get("demo_report", {})
            status = demo.get("overall_status", "unknown") if demo else "unknown"
            screenshots = demo.get("screenshot_count", 0) if demo else 0
            print(f"\nCycle {cycle_num} result: status={status}, "
                  f"cost=${result.get('cost_usd', 0):.2f}, "
                  f"screenshots={screenshots}")

        except BudgetExceeded as e:
            print(f"\nBudget exceeded in cycle {cycle_num}: {e}")
            break
        except Exception as e:
            log.exception("Cycle %d failed", cycle_num)
            print(f"\nCycle {cycle_num} failed: {e}")
            # Continue to next cycle — transient errors shouldn't stop us
            continue

    # Final completion check
    is_done, final_status = await _check_project_done(config)

    print(f"\n{'=' * 60}")
    print("AUTONOMOUS RUN COMPLETE")
    print(f"{'=' * 60}")
    print(f"Cycles run:    {len(cycle_results)}")
    print(f"Total cost:    ${total_cost:.2f}")
    print(f"Total tokens:  {total_tokens:,}")
    print(f"Project done:  {'YES' if is_done else 'NO'}")
    print(f"Final status:  {final_status}")

    return {
        "cycles_run": len(cycle_results),
        "total_cost_usd": total_cost,
        "total_tokens": total_tokens,
        "project_done": is_done,
        "final_status": final_status,
        "cycle_results": cycle_results,
    }
