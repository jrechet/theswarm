"""The cycle as a durable LangGraph (V2 runtime, M4).

`run_daily_cycle` used to be four hundred imperative lines, and a container
replaced mid-flight forgot all of them. Here the same phases are nodes of
one StateGraph, checkpointed after each one (SQLite in prod, memory
otherwise), so a cycle killed by a deploy resumes at the node after the
last one that finished — ``run_daily_cycle(resume=True)`` on the same
``cycle_id``.

What lives in the state is small and serialisable: counters, ids, PRs and
reviews as dicts, the report. Live objects — the GitHub client, the Claude
wrapper, the progress callback, the watchdog — travel in the graph's
runtime context (``Runtime[CycleRuntime]``), which LangGraph never
checkpoints. The agent graphs stay what they were: each phase node builds
one and reads its answer. Their builders are looked up on ``theswarm.cycle``
at call time, so the existing tests keep patching them there.

A node re-run after a crash between its effect and its checkpoint must be
safe: the breakdown skips stories already split, the Dev's picker skips
tasks in progress, a PR is reused for its branch, a review is keyed by
``number@sha``; the learnings and the cycle log are separate nodes so a
crash between them re-runs only the log.
"""

from __future__ import annotations

import asyncio
import contextvars
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime

from theswarm.config import CycleConfig, Phase, Role
from theswarm.cycle_budgets import BudgetExceeded, PhaseTimeout
from theswarm.domain.cycles.value_objects import PHASE_ROLE
from theswarm.infrastructure import tracing
from theswarm.tools.claude import ClaudeFatalError

log = logging.getLogger(__name__)

# Bump when a key changes meaning: a checkpoint from another version is
# not resumed (CycleNotResumable), never misread.
CYCLE_STATE_SCHEMA_VERSION = 1
# Two nodes per dev iteration, a handful around them; LangGraph's default
# of 25 would cut a five-iteration cycle short.
RECURSION_LIMIT = 200


class CycleNotResumable(Exception):
    """The thread has no usable checkpoint for this code."""


class CycleState(TypedDict, total=False):
    """Everything the graph checkpoints. Values, never objects."""

    schema_version: int
    cycle_id: str
    date: str
    iteration: int
    dev_outcome: str  # after dev_iter: "review" | "skip" | "end"
    dev_claims_open: bool
    attempted_tasks: list[int]
    attempted_without_pr: list[int]
    already_satisfied: list[int]  # tasks the Dev closed: the work was on main
    reviewed_prs: list[str]
    prs: list[dict]
    reviews: list[dict]
    merged_prs: list[int]
    held_prs: list[int]
    records: list[dict]  # {"agent", "tokens", "cost"} per phase, in order
    role_tokens: dict[str, int]
    total_cost: float
    daily_plan: str
    demo_report: dict | None
    daily_report: str
    requeued: list[int]
    result: dict | None
    learnings_written: bool
    cycle_logged: bool


@dataclass
class CycleRuntime:
    """The live half of a cycle — in the graph's context, never its state."""

    config: CycleConfig
    base_state: dict
    progress: Callable[[str, str], Awaitable[None]]
    raw_progress: Callable[[str, str], Awaitable[None]] | None = None
    checkpoint: Callable[[str, bool, dict], Awaitable[None]] | None = None
    watchdog: Any = None
    current_role: dict = field(default_factory=lambda: {"name": "System"})
    current_phase: dict = field(default_factory=lambda: {"name": "po_morning"})
    # True from the first Dev claim until the loop handed back what it did
    # not finish; the runner's `finally` reads it after a crash.
    dev_claims_open: bool = False

    async def announce(self, phase: str) -> None:
        """Tell the theater which phase runs now — a typed channel, not a
        heartbeat and not a log line (the bridge turns it into PhaseChanged)."""
        if self.raw_progress is None:
            return
        try:
            await self.raw_progress(PHASE_ROLE, phase)
        except Exception:  # noqa: BLE001 — a deaf listener never stops a cycle
            pass

    async def enter(self, phase: str) -> None:
        self.current_phase["name"] = phase
        await self.announce(phase)

    async def phase_checkpoint(self, phase: str, ok: bool, snapshot: dict) -> None:
        if self.checkpoint is not None:
            await self.checkpoint(phase, ok, snapshot)


def _cycle():
    """`theswarm.cycle`, looked up late: tests patch its builders."""
    from theswarm import cycle

    return cycle


def _invoke_agent(graph, state: dict) -> "asyncio.Task":
    """Run an agent graph *detached* from the cycle graph's runnable context.

    A compiled graph invoked inside a node inherits the parent's
    checkpointer and gets checkpointed as a subgraph — and the agent state
    carries live clients that msgpack cannot serialise (the first prod cycle
    on the durable graph, ddd989b4e51e, died in po_morning on
    "Type is not msgpack serializable: GitHubClient"). Compiling the agent
    graphs with ``checkpointer=False`` is not enough under
    ``durability="sync"`` (LangGraph: `'AsyncPregelLoop' object has no
    attribute '_put_checkpoint_fut'`). A fresh contextvars.Context leaves
    the parent's runnable config behind; the OpenTelemetry context is
    re-attached so the agent's node spans still nest under the phase.
    `asyncio.wait_for` (the phase budget) cancels the task like any other.
    """
    from opentelemetry import context as otel_context

    parent_span_context = otel_context.get_current()

    async def _run():
        token = otel_context.attach(parent_span_context)
        try:
            return await graph.ainvoke(state)
        finally:
            otel_context.detach(token)

    return asyncio.get_running_loop().create_task(_run(), context=contextvars.Context())


async def _run_phase(rt: CycleRuntime, phase_key: str, role: str, coro):
    """Run an awaitable with that phase's hard timeout. Surfaces PhaseTimeout."""
    # Read off `theswarm.cycle` at call time: tests swap that module's
    # PHASE_TIMEOUTS for a short one.
    timeout = _cycle().PHASE_TIMEOUTS.get(phase_key, 10 * 60)
    rt.current_role["name"] = role
    with tracing.span(
        f"phase.{phase_key}",
        **{"swarm.phase": phase_key, "swarm.role": role, "swarm.budget_s": timeout},
    ):
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError as exc:
            log.error("Phase %s exceeded %ds — aborting", phase_key, timeout)
            await rt.progress(role, f"⏱  Phase {phase_key} timed out after {timeout}s — aborting")
            raise PhaseTimeout(phase_key, timeout) from exc
        finally:
            # The phase is over either way: this role owes no further
            # heartbeat, so it must stop being judged idle.
            if rt.watchdog is not None:
                rt.watchdog.retire(role)


def _accounted(state: CycleState, agent: str, tokens: int, cost: float) -> dict:
    print(f"  -> {agent}: {tokens:,} tokens (${cost:.4f})")
    return {
        "records": [*state.get("records", []), {"agent": agent, "tokens": tokens, "cost": cost}],
        "total_cost": state.get("total_cost", 0.0) + cost,
    }


def _within_budget(rt: CycleRuntime, state: CycleState, role: Role, new_tokens: int) -> dict:
    role_tokens = dict(state.get("role_tokens", {}))
    role_tokens[role.value] = role_tokens.get(role.value, 0) + new_tokens
    budget = rt.config.token_budget.get(role, 0)
    if budget and role_tokens[role.value] > budget:
        raise BudgetExceeded(role.value, role_tokens[role.value], budget)
    return {"role_tokens": role_tokens}


# ── Nodes ────────────────────────────────────────────────────────────


async def prepare(state: CycleState, runtime: Runtime[CycleRuntime]) -> dict:
    rt = runtime.context
    if rt.config.is_real_mode and rt.base_state.get("github"):
        await rt.progress("System", "Checking branch protection…")
        await rt.base_state["github"].ensure_branch_protection()
    return {}


async def po_morning(state: CycleState, runtime: Runtime[CycleRuntime]) -> dict:
    rt = runtime.context
    await rt.enter("po_morning")
    await rt.progress("PO", "Starting daily planning…")
    po_state = await _run_phase(
        rt, "po_morning", "PO",
        _invoke_agent(_cycle().build_po_graph(), {**rt.base_state, "phase": Phase.MORNING.value}),
    )
    tokens, cost = po_state.get("tokens_used", 0), po_state.get("cost_usd", 0.0)
    budget = _within_budget(rt, state, Role.PO, tokens)
    await rt.phase_checkpoint("po_morning", True, {"tokens": tokens, "cost": cost})
    return {
        **_accounted(state, "po_morning", tokens, cost), **budget,
        "daily_plan": po_state.get("daily_plan", ""),
    }


async def techlead_breakdown(state: CycleState, runtime: Runtime[CycleRuntime]) -> dict:
    rt = runtime.context
    await rt.enter("techlead_breakdown")
    await rt.progress("TechLead", "Breaking down stories into tasks…")
    tl_state = await _run_phase(
        rt, "techlead_breakdown", "TechLead",
        _invoke_agent(_cycle().build_techlead_graph(), {**rt.base_state, "phase": "breakdown"}),
    )
    tokens, cost = tl_state.get("tokens_used", 0), tl_state.get("cost_usd", 0.0)
    budget = _within_budget(rt, state, Role.TECHLEAD, tokens)
    await rt.phase_checkpoint("techlead_breakdown", True, {"tokens": tokens, "cost": cost})
    return {**_accounted(state, "techlead_breakdown", tokens, cost), **budget}


async def _dev_iter_parallel(
    rt: CycleRuntime, state: CycleState, updates: dict, iteration: int,
    attempted: list[int], width: int,
) -> dict:
    """Up to ``width`` Dev graphs at once, each on its own task and worktree
    (V2 runtime, M5b; ``SWARM_DEV_PARALLELISM``).

    The pickers take turns behind one lock and skip what a sibling already
    claimed. A branch that raises is that task's failure, not the
    iteration's: ``implement_task`` has already handed its task back. A
    quota (``ClaudeFatalError``) still ends the cycle.
    """
    lock = asyncio.Lock()
    claimed: list[int] = []
    graphs = [
        _invoke_agent(_cycle().build_dev_graph(), {
            **rt.base_state,
            "phase": Phase.DEVELOPMENT.value,
            "attempted_tasks": attempted,
            "pick_lock": lock,
            "claimed_tasks": claimed,
        })
        for _ in range(width)
    ]
    await rt.progress("Dev", f"Up to {width} tasks side by side")
    try:
        results = await _run_phase(
            rt, "dev_iter", "Dev", asyncio.gather(*graphs, return_exceptions=True),
        )
    except PhaseTimeout:
        for graph in graphs:
            graph.cancel()
        await rt.progress("Dev", f"Iteration {iteration} timed out — moving on")
        return {**updates, "dev_outcome": "skip"}

    tokens, cost = 0, 0.0
    prs = list(state.get("prs", []))
    satisfied = list(state.get("already_satisfied", []))
    without = list(state.get("attempted_without_pr", []))
    worked = failed = repeated = opened = 0
    for result in results:
        if isinstance(result, ClaudeFatalError):
            await rt.progress("Dev", f"Fatal Claude error — aborting cycle: {str(result)[:160]}")
            raise result
        if isinstance(result, BaseException):
            failed += 1
            await rt.progress(
                "Dev", f"A task failed ({type(result).__name__}: {str(result)[:120]}) — handed back",
            )
            continue
        tokens += result.get("tokens_used", 0)
        cost += result.get("cost_usd", 0.0)
        pr, task = result.get("pr"), result.get("task")
        if pr:
            worked += 1
            opened += 1
            prs.append(pr)
            await rt.progress("Dev", f"PR #{pr['number']} opened: {pr['url']}")
            continue
        if task is None:
            continue
        worked += 1
        number = task["number"]
        if result.get("already_satisfied"):
            satisfied.append(number)
            await rt.progress("Dev", f"Task #{number} already satisfied on main — closed")
        else:
            await rt.progress("Dev", f"No PR produced for task #{number}")
        if number in without:
            repeated += 1
        else:
            without.append(number)

    updates.update(_accounted(state, f"dev_iter{iteration}", tokens, cost))
    updates.update(_within_budget(rt, state, Role.DEV, tokens))
    updates.update({"prs": prs, "already_satisfied": satisfied, "attempted_without_pr": without})
    if worked == 0 and failed == 0:
        await rt.progress("Dev", "No more ready tasks — ending dev loop")
        return {**updates, "dev_outcome": "end"}
    if worked == 0:
        return {**updates, "dev_outcome": "skip"}
    if not opened and repeated == worked:
        await rt.progress("Dev", "Every task produced no changes twice — ending dev loop")
        return {**updates, "dev_outcome": "end"}
    return {**updates, "dev_outcome": "review"}


async def dev_iter(state: CycleState, runtime: Runtime[CycleRuntime]) -> dict:
    """One Dev iteration. Sets ``dev_outcome`` for the router: review the
    PRs, skip to the next iteration, or end the loop."""
    rt = runtime.context
    iteration = state.get("iteration", 0) + 1
    updates: dict = {"iteration": iteration}
    if iteration == 1:
        await rt.enter("dev_loop")
        rt.dev_claims_open = True
        updates["dev_claims_open"] = True
        await rt.progress("Dev", "Starting development loop…")
    await rt.announce("dev_iter")
    await rt.progress("Dev", f"Iteration {iteration}/{_cycle().MAX_DEV_ITERATIONS} — picking next task…")

    # Passed by reference so `pick_task` can record an attempt that the
    # iteration never returns from — the picker reads it to put a task that
    # already failed behind the ones nobody has tried. Returned explicitly:
    # an in-place mutation is invisible to the checkpoint.
    attempted = list(state.get("attempted_tasks", []))
    updates["attempted_tasks"] = attempted

    from theswarm.tools.git import dev_parallelism

    width = dev_parallelism()
    if width > 1:
        return await _dev_iter_parallel(rt, state, updates, iteration, attempted, width)

    async def _invoke():
        return await _run_phase(
            rt, "dev_iter", "Dev",
            _invoke_agent(_cycle().build_dev_graph(), {
                **rt.base_state,
                "phase": Phase.DEVELOPMENT.value,
                "attempted_tasks": attempted,
            }),
        )

    # One retry on transient errors (git, network, etc). PhaseTimeout
    # already implies a hung Claude call; don't retry that.
    try:
        dev_state = await _invoke()
    except PhaseTimeout:
        await rt.progress("Dev", f"Iteration {iteration} timed out — moving on")
        return {**updates, "dev_outcome": "skip"}
    except ClaudeFatalError as exc:
        await rt.progress("Dev", f"Fatal Claude error — aborting cycle: {str(exc)[:160]}")
        raise
    except Exception as exc:  # noqa: BLE001 — retried once, then skipped
        msg = f"{type(exc).__name__}: {str(exc)[:160]}"
        await rt.progress("Dev", f"Iteration {iteration} failed ({msg}) — retrying once")
        log.warning("Dev iteration %d failed, retrying: %s", iteration, exc)
        try:
            dev_state = await _invoke()
        except PhaseTimeout:
            await rt.progress("Dev", f"Iteration {iteration} retry timed out — moving on")
            return {**updates, "dev_outcome": "skip"}
        except ClaudeFatalError as exc2:
            await rt.progress("Dev", f"Fatal Claude error — aborting cycle: {str(exc2)[:160]}")
            raise
        except Exception as exc2:  # noqa: BLE001
            msg2 = f"{type(exc2).__name__}: {str(exc2)[:160]}"
            await rt.progress("Dev", f"Iteration {iteration} retry also failed ({msg2}) — skipping")
            log.error("Dev iteration %d retry failed: %s", iteration, exc2)
            return {**updates, "dev_outcome": "skip"}

    tokens, cost = dev_state.get("tokens_used", 0), dev_state.get("cost_usd", 0.0)
    updates.update(_accounted(state, f"dev_iter{iteration}", tokens, cost))
    updates.update(_within_budget(rt, state, Role.DEV, tokens))

    pr = dev_state.get("pr")
    if pr:
        updates["prs"] = [*state.get("prs", []), pr]
        await rt.progress("Dev", f"PR #{pr['number']} opened: {pr['url']}")
        return {**updates, "dev_outcome": "review"}

    task = dev_state.get("task")
    if task is None:
        await rt.progress("Dev", "No more ready tasks — ending dev loop")
        return {**updates, "dev_outcome": "end"}
    # A task that yields no PR twice yields none at all: a verification
    # story with nothing to change, or work the model cannot complete.
    number = task["number"]
    if dev_state.get("already_satisfied"):
        # Closed by the Dev, not failed: the result says why no PR came
        # out, and the harness scores it already delivered, not a
        # regression (cycle 874f575645f2 closed #286-#288 this way).
        updates["already_satisfied"] = [*state.get("already_satisfied", []), number]
        await rt.progress("Dev", f"Task #{number} already satisfied on main — closed")
    without = list(state.get("attempted_without_pr", []))
    if number in without:
        await rt.progress("Dev", f"Task #{number} produced no changes twice — ending dev loop")
        return {**updates, "dev_outcome": "end"}
    without.append(number)
    if not dev_state.get("already_satisfied"):
        await rt.progress("Dev", f"No PR produced for task #{number}")
    return {**updates, "attempted_without_pr": without, "dev_outcome": "review"}


async def techlead_review(state: CycleState, runtime: Runtime[CycleRuntime]) -> dict:
    rt = runtime.context
    await rt.announce("techlead_review")
    await rt.progress("TechLead", "Reviewing open PRs…")
    # The PRs reviewed this cycle, at the head seen: a held or commented PR
    # is not read again unless something was pushed to it.
    reviewed = list(state.get("reviewed_prs", []))
    iteration = state.get("iteration", 0)
    try:
        tl_state = await _run_phase(
            rt, "techlead_review", "TechLead",
            _invoke_agent(_cycle().build_techlead_graph(), {
                **rt.base_state, "phase": "review_loop", "reviewed_prs": reviewed,
            }),
        )
    except PhaseTimeout:
        await rt.progress("TechLead", "Review timed out — leaving PRs for next cycle")
        return {"reviewed_prs": reviewed}

    tokens, cost = tl_state.get("tokens_used", 0), tl_state.get("cost_usd", 0.0)
    updates = {
        **_accounted(state, f"techlead_review_iter{iteration}", tokens, cost),
        **_within_budget(rt, state, Role.TECHLEAD, tokens),
        "reviewed_prs": list(tl_state.get("reviewed_prs", reviewed)),
    }

    reviews = tl_state.get("reviews", [])
    updates["reviews"] = [*state.get("reviews", []), *reviews]
    merged = list(tl_state.get("merged_prs", []))
    updates["merged_prs"] = [*state.get("merged_prs", []), *merged]
    for r in reviews:
        await rt.progress("TechLead", f"PR #{r['pr_number']}: {r['decision']}")
    for r in reviews:
        if r.get("sent_back"):
            await rt.progress(
                "TechLead", f"PR #{r['pr_number']}: changes requested — task back to the Dev",
            )
    for number in tl_state.get("skipped_prs", []):
        await rt.progress(
            "TechLead", f"Review of PR #{number} unavailable — left for the next pass",
        )
    if merged:
        await rt.progress("TechLead", f"Merged: {merged}")
    held = list(tl_state.get("held_prs", []))
    updates["held_prs"] = [*state.get("held_prs", []), *held]
    if held:
        await rt.progress(
            "TechLead",
            f"Approved, not merged: {held} — merging {rt.config.github_repo} "
            "redeploys the swarm and would end this cycle mid-flight",
        )
    # Pull latest into workspace so the next iteration builds on merged code
    if merged:
        await _cycle()._pull_latest(rt.config)
    return updates


def _after_dev_iter(state: CycleState) -> str:
    outcome = state.get("dev_outcome", "end")
    if outcome == "review":
        return "techlead_review"
    if outcome == "skip" and state.get("iteration", 0) < _cycle().MAX_DEV_ITERATIONS:
        return "dev_iter"
    return "dev_loop_end"


def _after_review(state: CycleState) -> str:
    return "dev_iter" if state.get("iteration", 0) < _cycle().MAX_DEV_ITERATIONS else "dev_loop_end"


async def dev_loop_end(state: CycleState, runtime: Runtime[CycleRuntime]) -> dict:
    """Hand back anything still marked in-progress. The loop can end with
    work claimed but unfinished — the iteration cap, a task that produced
    nothing twice, a timeout — and a task left in-progress reads as
    "someone is on it" when nobody is (prod cycle 751202be0c3a)."""
    rt = runtime.context
    requeued = await _cycle()._requeue_unfinished(rt.config)
    rt.dev_claims_open = False
    # Worktrees a task left behind (no PR, a timeout, a crash): the
    # branches stay, the checkouts go (M5b).
    workspace = getattr(rt.config, "workspace_dir", "") or ""
    if workspace:
        try:
            from theswarm.tools import git as git_ops

            await git_ops.prune_worktrees(workspace)
        except Exception:  # noqa: BLE001 - tidying never fails a cycle
            log.exception("Pruning worktrees of %s failed", workspace)
    if requeued:
        await rt.progress(
            "Dev",
            "Handing back " + ", ".join(f"#{n}" for n in requeued) + " — claimed but not finished",
        )
    await rt.phase_checkpoint("dev_loop", True, {
        "prs_opened": [p.get("number") for p in state.get("prs", []) if isinstance(p, dict)],
        "reviews": len(state.get("reviews", [])),
        "requeued": requeued,
    })
    return {"dev_claims_open": False, "requeued": requeued}


async def qa(state: CycleState, runtime: Runtime[CycleRuntime]) -> dict:
    rt = runtime.context
    await rt.enter("qa")
    await rt.progress("QA", "Running tests + security scan…")
    try:
        qa_state = await _run_phase(
            rt, "qa", "QA",
            _invoke_agent(_cycle().build_qa_graph(), {**rt.base_state, "phase": Phase.DEMO.value}),
        )
    except PhaseTimeout:
        qa_state = {}
    tokens, cost = qa_state.get("tokens_used", 0), qa_state.get("cost_usd", 0.0)
    budget = _within_budget(rt, state, Role.QA, tokens)
    await rt.phase_checkpoint("qa", bool(qa_state), {"tokens": tokens, "cost": cost})
    return {
        **_accounted(state, "qa", tokens, cost), **budget,
        "demo_report": qa_state.get("demo_report"),
    }


async def po_evening(state: CycleState, runtime: Runtime[CycleRuntime]) -> dict:
    rt = runtime.context
    await rt.enter("po_evening")
    await rt.progress("PO", "Generating daily report…")
    try:
        po_ev_state = await _run_phase(
            rt, "po_evening", "PO",
            _invoke_agent(_cycle().build_po_graph(), {
                **rt.base_state,
                "phase": Phase.EVENING.value,
                "demo_report": state.get("demo_report"),
            }),
        )
    except PhaseTimeout:
        po_ev_state = {}
    tokens, cost = po_ev_state.get("tokens_used", 0), po_ev_state.get("cost_usd", 0.0)
    await rt.phase_checkpoint("po_evening", bool(po_ev_state), {"tokens": tokens, "cost": cost})
    return {
        **_accounted(state, "po_evening", tokens, cost),
        "daily_report": po_ev_state.get("daily_report", ""),
    }


async def merge_held(state: CycleState, runtime: Runtime[CycleRuntime]) -> dict:
    """What the review phase approved but held back. On SELF_REPO the review
    refuses to merge, because the redeploy that follows would end the cycle
    mid-review; here every phase is done, so approved work lands."""
    rt = runtime.context
    held = sorted(set(state.get("held_prs", [])))
    if not held:
        return {}
    newly = await _cycle()._merge_held_prs(rt.base_state.get("github"), held, rt.progress)
    return {
        "merged_prs": [*state.get("merged_prs", []), *newly],
        "held_prs": [n for n in state.get("held_prs", []) if n not in newly],
    }


async def finish(state: CycleState, runtime: Runtime[CycleRuntime]) -> dict:
    rt = runtime.context
    records = state.get("records", [])
    total_tokens = sum(int(r.get("tokens", 0)) for r in records)
    total_cost = state.get("total_cost", 0.0)
    prs = state.get("prs", [])
    merged = sorted(set(state.get("merged_prs", [])))
    held = sorted(set(state.get("held_prs", [])))

    print(f"\n{'=' * 60}")
    print("CYCLE COMPLETE")
    print(f"{'=' * 60}")
    print(f"Tokens total : {total_tokens:,}")
    print(f"\nClaude API cost: ${total_cost:.2f}")
    print(f"PRs opened: {len(prs)}")
    print(f"PRs merged: {len(merged)}")
    if held:
        print(f"PRs held for a human to merge: {held}")

    await rt.progress("PO", "Cycle complete!")

    from theswarm.tools.claude import _resolve_backend_mode

    result = {
        "date": state.get("date", ""),
        "backend": _resolve_backend_mode(),
        "tokens": total_tokens,
        "cost_usd": total_cost,
        "prs": prs,
        "already_satisfied": sorted(set(state.get("already_satisfied", []))),
        "reviews": state.get("reviews", []),
        "merged_prs": merged,
        "held_prs": held,
        "demo_report": state.get("demo_report"),
        "daily_report": state.get("daily_report", ""),
    }
    updates: dict = {"result": result}
    # --- MEMORY: retrospective + learnings ---
    if rt.config.is_real_mode and not state.get("learnings_written"):
        await _cycle()._write_cycle_learnings(rt.base_state, result, rt.progress)
        updates["learnings_written"] = True
    return updates


async def cycle_log(state: CycleState, runtime: Runtime[CycleRuntime]) -> dict:
    """The cycle history line — its own node, so a crash after the
    learnings re-runs only this."""
    if state.get("cycle_logged"):
        return {}
    from theswarm import cycle_log as cycle_log_mod

    await cycle_log_mod.append_cycle_log(runtime.context.config, state.get("result") or {})
    return {"cycle_logged": True}


# ── The graph ────────────────────────────────────────────────────────


def build_cycle_graph(checkpointer=None):
    graph = StateGraph(CycleState, context_schema=CycleRuntime)
    for name, fn in (
        ("prepare", prepare),
        ("po_morning", po_morning),
        ("techlead_breakdown", techlead_breakdown),
        ("dev_iter", dev_iter),
        ("techlead_review", techlead_review),
        ("dev_loop_end", dev_loop_end),
        ("qa", qa),
        ("po_evening", po_evening),
        ("merge_held", merge_held),
        ("finish", finish),
        ("cycle_log", cycle_log),
    ):
        graph.add_node(name, fn)
    graph.set_entry_point("prepare")
    graph.add_edge("prepare", "po_morning")
    graph.add_edge("po_morning", "techlead_breakdown")
    graph.add_edge("techlead_breakdown", "dev_iter")
    graph.add_conditional_edges("dev_iter", _after_dev_iter, {
        "techlead_review": "techlead_review",
        "dev_iter": "dev_iter",
        "dev_loop_end": "dev_loop_end",
    })
    graph.add_conditional_edges("techlead_review", _after_review, {
        "dev_iter": "dev_iter",
        "dev_loop_end": "dev_loop_end",
    })
    graph.add_edge("dev_loop_end", "qa")
    graph.add_edge("qa", "po_evening")
    graph.add_edge("po_evening", "merge_held")
    graph.add_edge("merge_held", "finish")
    graph.add_edge("finish", "cycle_log")
    graph.add_edge("cycle_log", END)
    return graph.compile(checkpointer=checkpointer)


def initial_state(cycle_id: str, date: str) -> CycleState:
    return {
        "schema_version": CYCLE_STATE_SCHEMA_VERSION,
        "cycle_id": cycle_id,
        "date": date,
        "iteration": 0,
        "dev_outcome": "",
        "dev_claims_open": False,
        "attempted_tasks": [],
        "attempted_without_pr": [],
        "already_satisfied": [],
        "reviewed_prs": [],
        "prs": [],
        "reviews": [],
        "merged_prs": [],
        "held_prs": [],
        "records": [],
        "role_tokens": {},
        "total_cost": 0.0,
        "daily_plan": "",
        "demo_report": None,
        "daily_report": "",
        "requeued": [],
        "result": None,
        "learnings_written": False,
        "cycle_logged": False,
    }


async def run_cycle_graph(
    runtime: CycleRuntime, *, cycle_id: str, checkpointer=None, resume: bool = False,
    date: str = "",
) -> dict:
    """Start a cycle on its thread, or continue an interrupted one."""
    if checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver

        checkpointer = MemorySaver()
    graph = build_cycle_graph(checkpointer)
    thread = {"configurable": {"thread_id": cycle_id}, "recursion_limit": RECURSION_LIMIT}

    if resume:
        snapshot = await graph.aget_state(thread)
        values = dict(snapshot.values or {}) if snapshot is not None else {}
        if not values:
            raise CycleNotResumable(f"cycle {cycle_id}: no checkpoint to resume from")
        version = values.get("schema_version")
        if version != CYCLE_STATE_SCHEMA_VERSION:
            raise CycleNotResumable(
                f"cycle {cycle_id}: checkpoint schema v{version}, this code is "
                f"v{CYCLE_STATE_SCHEMA_VERSION} — not resumed"
            )
        if values.get("result") is not None and values.get("cycle_logged"):
            return values["result"]
        runtime.dev_claims_open = bool(values.get("dev_claims_open"))
        runtime.current_phase["name"] = _phase_of(values)
        log.info("Resuming cycle %s at iteration %s", cycle_id, values.get("iteration", 0))
        if runtime.dev_claims_open:
            # The iteration that died had claimed a task (`status:in-progress`)
            # and never handed it back; the picker skips claimed tasks, so a
            # resume would find "nothing ready" and go straight to QA. Give
            # the claims back first — the Dev picks them up again.
            requeued = await _cycle()._requeue_unfinished(runtime.config)
            if requeued:
                await runtime.progress(
                    "Dev", "Resumed — handing back " + ", ".join(f"#{n}" for n in requeued)
                    + " claimed by the interrupted iteration",
                )
        final = await graph.ainvoke(None, thread, context=runtime, durability="sync")
    else:
        final = await graph.ainvoke(
            initial_state(cycle_id, date), thread, context=runtime, durability="sync",
        )
    return final.get("result") or {}


def _phase_of(values: dict) -> str:
    """A best guess of the phase a resumed thread is in, for the failed
    checkpoint the runner writes if the resume dies too."""
    if values.get("result") is not None:
        return "po_evening"
    if values.get("daily_report"):
        return "po_evening"
    if values.get("requeued") or values.get("demo_report") is not None:
        return "qa"
    if values.get("iteration", 0):
        return "dev_loop"
    if values.get("daily_plan"):
        return "techlead_breakdown"
    return "po_morning"
