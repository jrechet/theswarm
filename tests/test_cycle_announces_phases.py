"""A cycle tells the theater which phase it is in, in order.

Through on_progress(PHASE_ROLE, name): not a heartbeat, not a log line,
a typed channel. Sub-phases go through it too — the graph needs to see the
Dev iterate and the TechLead come back to review — while checkpoints keep
to the canonical phases and never hear about them.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from theswarm.config import CycleConfig
from theswarm.cycle import run_daily_cycle
from theswarm.domain.cycles.checkpoint import PHASE_ORDER
from theswarm.domain.cycles.value_objects import PHASE_ROLE

STUB = {"tokens_used": 0, "cost_usd": 0.0, "result": "ok"}
QA = {**STUB, "demo_report": {"overall_status": "green", "date": "2026-09-15"}}


def _graph(state):
    g = MagicMock()
    g.ainvoke = AsyncMock(return_value=state)
    return g


async def _run(dev_state):
    config = CycleConfig(github_repo="owner/repo")
    github = MagicMock()
    github.ensure_branch_protection = AsyncMock()
    github.get_open_prs = AsyncMock(return_value=[])
    base_state = {
        "team_id": "t", "github_repo": "owner/repo",
        "github": github, "claude": MagicMock(), "workspace": "/nowhere",
    }
    calls: list[tuple[str, str]] = []

    async def track(role: str, message: str) -> None:
        calls.append((role, message))

    with patch("theswarm.cycle.build_po_graph", MagicMock(return_value=_graph(STUB))), \
         patch("theswarm.cycle.build_techlead_graph", MagicMock(return_value=_graph(STUB))), \
         patch("theswarm.cycle.build_dev_graph", MagicMock(return_value=_graph(dev_state))), \
         patch("theswarm.cycle.build_qa_graph", MagicMock(return_value=_graph(QA))), \
         patch("theswarm.cycle._ensure_workspace", new_callable=AsyncMock), \
         patch("theswarm.cycle._pull_latest", new_callable=AsyncMock), \
         patch("theswarm.cycle._build_base_state", return_value=base_state), \
         patch("theswarm.cycle_log.append_cycle_log", new_callable=AsyncMock), \
         patch("theswarm.cycle._write_cycle_learnings", new_callable=AsyncMock), \
         patch("theswarm.tools.git.cleanup_workspace", new_callable=AsyncMock):
        await run_daily_cycle(config, on_progress=track)
    return calls


def _phases(calls):
    return [message for role, message in calls if role == PHASE_ROLE]


async def test_a_cycle_with_nothing_to_build_announces_every_phase_once():
    nothing_to_do = {**STUB, "task": None, "pr": None}

    phases = _phases(await _run(nothing_to_do))

    assert phases == [
        "po_morning", "techlead_breakdown", "dev_loop", "dev_iter", "qa", "po_evening",
    ]


async def test_every_iteration_and_review_is_announced():
    one_pr_each_time = {
        **STUB, "task": {"number": 5}, "pr": {"number": 1, "url": "https://x/pull/1"},
    }

    phases = _phases(await _run(one_pr_each_time))

    loop = phases[phases.index("dev_loop") + 1: phases.index("qa")]
    assert loop == ["dev_iter", "techlead_review"] * 5


async def test_the_canonical_phases_arrive_in_checkpoint_order():
    nothing_to_do = {**STUB, "task": None, "pr": None}

    phases = _phases(await _run(nothing_to_do))

    canonical = [p for p in phases if p in PHASE_ORDER]
    assert canonical == list(PHASE_ORDER)


async def test_announcements_are_not_agent_messages():
    """No agent is called 'phase': the watchdog and the feed never see one."""
    nothing_to_do = {**STUB, "task": None, "pr": None}

    calls = await _run(nothing_to_do)

    roles = {role for role, _ in calls}
    assert PHASE_ROLE in roles
    assert "Phase" not in roles


async def test_without_a_listener_the_cycle_still_runs():
    config = CycleConfig(github_repo="owner/repo")
    github = MagicMock()
    github.ensure_branch_protection = AsyncMock()
    github.get_open_prs = AsyncMock(return_value=[])
    base_state = {
        "team_id": "t", "github_repo": "owner/repo",
        "github": github, "claude": MagicMock(), "workspace": "/nowhere",
    }
    with patch("theswarm.cycle.build_po_graph", MagicMock(return_value=_graph(STUB))), \
         patch("theswarm.cycle.build_techlead_graph", MagicMock(return_value=_graph(STUB))), \
         patch("theswarm.cycle.build_dev_graph", MagicMock(return_value=_graph({**STUB, "task": None, "pr": None}))), \
         patch("theswarm.cycle.build_qa_graph", MagicMock(return_value=_graph(QA))), \
         patch("theswarm.cycle._ensure_workspace", new_callable=AsyncMock), \
         patch("theswarm.cycle._pull_latest", new_callable=AsyncMock), \
         patch("theswarm.cycle._build_base_state", return_value=base_state), \
         patch("theswarm.cycle_log.append_cycle_log", new_callable=AsyncMock), \
         patch("theswarm.cycle._write_cycle_learnings", new_callable=AsyncMock), \
         patch("theswarm.tools.git.cleanup_workspace", new_callable=AsyncMock):
        result = await run_daily_cycle(config, on_progress=None)

    assert "date" in result
