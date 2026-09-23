"""V2 runtime, M1: what the SDK backend streams reaches the theater as the
running role's progress (cycle.py wires ClaudeCLI.on_event to _progress).

A Dev call's "Read src/x.py" must show up under Dev, a PO call's under PO;
the watchdog hears them as heartbeats, so a long implementation no longer
looks idle.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from theswarm.config import CycleConfig
from theswarm.cycle import run_daily_cycle


def _graph_that_emits(state_key_message: str, return_state: dict) -> MagicMock:
    graph = MagicMock()

    async def ainvoke(state):
        claude = state.get("claude")
        if claude is not None and claude.on_event is not None:
            await claude.on_event(state_key_message)
        return return_state

    graph.ainvoke = AsyncMock(side_effect=ainvoke)
    return graph


async def test_sdk_events_are_reported_under_the_running_role(tmp_path):
    config = CycleConfig(github_repo="owner/repo", team_id="t", workspace_dir=str(tmp_path))
    fake_claude = SimpleNamespace(on_event=None)
    mock_github = MagicMock()
    mock_github.ensure_branch_protection = AsyncMock()
    mock_github.get_open_prs = AsyncMock(return_value=[])
    base_state = {
        "team_id": "t", "github_repo": "owner/repo",
        "github": mock_github, "claude": fake_claude, "workspace": str(tmp_path),
    }
    heard: list[tuple[str, str]] = []

    async def on_progress(role: str, message: str) -> None:
        heard.append((role, message))

    po = _graph_that_emits("Read docs/plan.md", {"tokens_used": 1, "cost_usd": 0.0, "daily_plan": "p"})
    tl = _graph_that_emits("Grep \"Parent: #\"", {"tokens_used": 1, "cost_usd": 0.0})
    dev = _graph_that_emits("Edit src/x.py", {"tokens_used": 1, "cost_usd": 0.0, "task": None, "pr": None})
    qa = _graph_that_emits("Bash: pytest -q", {
        "tokens_used": 1, "cost_usd": 0.0,
        "demo_report": {"overall_status": "green", "date": "2026-09-23"},
    })

    with patch("theswarm.cycle.build_po_graph", return_value=po), \
         patch("theswarm.cycle.build_techlead_graph", return_value=tl), \
         patch("theswarm.cycle.build_dev_graph", return_value=dev), \
         patch("theswarm.cycle.build_qa_graph", return_value=qa), \
         patch("theswarm.cycle._ensure_workspace", new=AsyncMock()), \
         patch("theswarm.cycle._pull_latest", new=AsyncMock()), \
         patch("theswarm.cycle._build_base_state", return_value=base_state), \
         patch("theswarm.cycle_log.append_cycle_log", new_callable=AsyncMock), \
         patch("theswarm.cycle._write_cycle_learnings", new_callable=AsyncMock), \
         patch("theswarm.tools.git.cleanup_workspace", new_callable=AsyncMock):
        await run_daily_cycle(config, on_progress=on_progress)

    assert fake_claude.on_event is not None
    assert ("PO", "Read docs/plan.md") in heard
    assert ("TechLead", "Grep \"Parent: #\"") in heard
    assert ("Dev", "Edit src/x.py") in heard
    assert ("QA", "Bash: pytest -q") in heard
