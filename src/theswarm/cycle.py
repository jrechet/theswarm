"""Orchestrate one full daily cycle: morning → dev → demo → report."""

from __future__ import annotations

import logging
from datetime import datetime

from theswarm.agents.dev import build_dev_graph
from theswarm.agents.po import build_po_graph
from theswarm.agents.qa import build_qa_graph
from theswarm.agents.techlead import build_techlead_graph
from theswarm.config import CycleConfig, Phase, Role
from theswarm.token_counter import TokenTracker

log = logging.getLogger(__name__)

MAX_DEV_ITERATIONS = 5  # safety cap per cycle


class BudgetExceeded(Exception):
    """Raised when a role exceeds its token budget."""
    def __init__(self, role: str, used: int, budget: int) -> None:
        self.role = role
        self.used = used
        self.budget = budget
        super().__init__(f"{role} exceeded token budget: {used:,} > {budget:,}")


async def _write_cycle_learnings(base_state: dict, qa_state: dict, reviews: list[dict], _progress) -> None:
    """Write cycle learnings to AGENT_MEMORY.md after QA completes."""
    from theswarm.memory import append_to_memory_batch

    github = base_state.get("github")
    if not github:
        return

    await _progress("Memory", "Writing cycle learnings…")

    entries = []

    # QA: record security scan results
    security = qa_state.get("security_scan", {})
    semgrep = security.get("semgrep", {})
    if semgrep.get("findings"):
        for finding in semgrep["findings"][:3]:  # max 3
            entries.append((
                "Erreurs à éviter",
                f"Semgrep: {finding.get('check_id', 'unknown')} in {finding.get('path', '?')}",
                "QA",
            ))

    # QA: record coverage
    coverage = security.get("coverage_pct")
    if coverage is not None:
        entries.append((
            "Stack technique",
            f"Code coverage: {coverage}%",
            "QA",
        ))

    # TechLead: record review patterns
    changes_requested = [r for r in reviews if r.get("decision") == "REQUEST_CHANGES"]
    for r in changes_requested[:2]:  # max 2
        issues = r.get("issues", [])
        for issue in issues[:1]:  # just the main issue
            entries.append((
                "Erreurs à éviter",
                f"PR #{r['pr_number']}: {issue.get('description', 'review issue')[:100]}",
                "TechLead",
            ))

    if entries:
        await append_to_memory_batch(github, entries)


def _build_base_state(config: CycleConfig) -> dict:
    """Build the base state dict, wiring real clients if in real mode."""
    state: dict = {
        "team_id": config.team_id,
        "github_repo": config.github_repo,
        "github": None,
        "claude": None,
        "workspace": None,
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


async def _pull_latest(config: CycleConfig) -> None:
    """Pull latest main into the workspace (after a merge)."""
    if not config.is_real_mode:
        return

    from theswarm.tools.git import _run_git
    await _run_git("checkout", "main", cwd=config.workspace_dir, check=False)
    await _run_git("pull", "--ff-only", cwd=config.workspace_dir, check=False)


async def run_daily_cycle(config: CycleConfig, on_progress=None) -> dict:
    """Run one complete daily cycle and return the summary.

    Args:
        config: Cycle configuration.
        on_progress: Optional async callback ``(role, message) -> None`` for live updates.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    tracker = TokenTracker()
    total_cost = 0.0
    all_prs: list[dict] = []
    all_reviews: list[dict] = []

    async def _progress(role: str, message: str) -> None:
        log.info("[%s] %s", role, message)
        print(f"[{role}] {message}")
        if on_progress:
            try:
                await on_progress(role, message)
            except Exception:
                pass

    # Per-role token accumulators for budget enforcement
    role_tokens: dict[str, int] = {r.value: 0 for r in Role}

    def _check_budget(role: Role, new_tokens: int) -> None:
        role_tokens[role.value] += new_tokens
        budget = config.token_budget.get(role, 0)
        if budget and role_tokens[role.value] > budget:
            raise BudgetExceeded(role.value, role_tokens[role.value], budget)

    print(f"\n{'=' * 60}")
    print(f"SWARM CYCLE — {today}")
    print(f"{'=' * 60}\n")

    # Prepare workspace
    await _ensure_workspace(config)
    base_state = _build_base_state(config)

    # Ensure branch protection on first run
    if config.is_real_mode and base_state.get("github"):
        await _progress("System", "Checking branch protection…")
        await base_state["github"].ensure_branch_protection()

    # --- MORNING: PO daily planning ---
    await _progress("PO", "Starting daily planning…")
    po = build_po_graph()
    po_state = await po.ainvoke({**base_state, "phase": Phase.MORNING.value})
    po_cost = po_state.get("cost_usd", 0.0)
    tracker.record("po_morning", po_state.get("tokens_used", 0), po_cost)
    total_cost += po_cost
    _check_budget(Role.PO, po_state.get("tokens_used", 0))

    # --- MORNING: Tech Lead story breakdown ---
    await _progress("TechLead", "Breaking down stories into tasks…")
    tl = build_techlead_graph()
    tl_state = await tl.ainvoke({**base_state, "phase": "breakdown"})
    tl_bd_cost = tl_state.get("cost_usd", 0.0)
    tracker.record("techlead_breakdown", tl_state.get("tokens_used", 0), tl_bd_cost)
    total_cost += tl_bd_cost
    _check_budget(Role.TECHLEAD, tl_state.get("tokens_used", 0))

    # --- DEVELOPMENT: Dev implements → TechLead reviews → repeat ---
    await _progress("Dev", "Starting development loop…")
    for iteration in range(1, MAX_DEV_ITERATIONS + 1):
        await _progress("Dev", f"Iteration {iteration}/{MAX_DEV_ITERATIONS} — picking next task…")
        dev = build_dev_graph()
        dev_state = await dev.ainvoke({**base_state, "phase": Phase.DEVELOPMENT.value})
        dev_cost = dev_state.get("cost_usd", 0.0)
        dev_tokens = dev_state.get("tokens_used", 0)
        tracker.record(f"dev_iter{iteration}", dev_tokens, dev_cost)
        total_cost += dev_cost
        _check_budget(Role.DEV, dev_tokens)

        pr = dev_state.get("pr")
        if pr:
            all_prs.append(pr)
            await _progress("Dev", f"PR #{pr['number']} opened: {pr['url']}")
        else:
            task = dev_state.get("task")
            if task is None:
                await _progress("Dev", "No more ready tasks — ending dev loop")
                break
            await _progress("Dev", f"No PR produced for task #{task['number']}")

        # TechLead reviews and merges
        await _progress("TechLead", "Reviewing open PRs…")
        tl_review = build_techlead_graph()
        tl_state = await tl_review.ainvoke({**base_state, "phase": "review_loop"})
        tl_cost = tl_state.get("cost_usd", 0.0)
        tl_tokens = tl_state.get("tokens_used", 0)
        tracker.record(f"techlead_review_iter{iteration}", tl_tokens, tl_cost)
        total_cost += tl_cost
        _check_budget(Role.TECHLEAD, tl_tokens)

        reviews = tl_state.get("reviews", [])
        all_reviews.extend(reviews)
        merged = tl_state.get("merged_prs", [])
        for r in reviews:
            await _progress("TechLead", f"PR #{r['pr_number']}: {r['decision']}")
        if merged:
            await _progress("TechLead", f"Merged: {merged}")

        # Pull latest into workspace so next iteration builds on merged code
        if merged:
            await _pull_latest(config)

    # --- DEMO: QA generates demo ---
    await _progress("QA", "Running tests + security scan…")
    qa = build_qa_graph()
    qa_state = await qa.ainvoke({**base_state, "phase": Phase.DEMO.value})
    qa_cost = qa_state.get("cost_usd", 0.0)
    tracker.record("qa", qa_state.get("tokens_used", 0), qa_cost)
    total_cost += qa_cost
    _check_budget(Role.QA, qa_state.get("tokens_used", 0))

    # --- MEMORY: write learnings from the cycle ---
    if config.is_real_mode:
        await _write_cycle_learnings(base_state, qa_state, all_reviews, _progress)

    # --- EVENING: PO validates + reports ---
    await _progress("PO", "Generating daily report…")
    po_evening = build_po_graph()
    po_ev_state = await po_evening.ainvoke({
        **base_state,
        "phase": Phase.EVENING.value,
        "demo_report": qa_state.get("demo_report"),
    })
    po_ev_cost = po_ev_state.get("cost_usd", 0.0)
    tracker.record("po_evening", po_ev_state.get("tokens_used", 0), po_ev_cost)
    total_cost += po_ev_cost

    # --- SUMMARY ---
    print(f"\n{'=' * 60}")
    print("CYCLE COMPLETE")
    print(f"{'=' * 60}")
    tracker.print_summary()
    print(f"\nClaude API cost: ${total_cost:.2f}")
    print(f"PRs opened: {len(all_prs)}")
    print(f"PRs merged: {sum(1 for r in all_reviews if r.get('decision') == 'APPROVE')}")

    await _progress("PO", "Cycle complete!")

    result = {
        "date": today,
        "tokens": tracker.total_tokens,
        "cost_usd": total_cost,
        "prs": all_prs,
        "reviews": all_reviews,
        "demo_report": qa_state.get("demo_report"),
        "daily_report": po_ev_state.get("daily_report", ""),
    }

    # --- PERSIST: write cycle history ---
    from theswarm.cycle_log import append_cycle_log
    await append_cycle_log(config, result)

    # --- CLEANUP: remove workspace ---
    if config.is_real_mode:
        from theswarm.tools.git import cleanup_workspace
        await cleanup_workspace(config.workspace_dir)

    return result


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
