"""The cycle's result names the sub-tasks the Dev closed as already satisfied.

Cycle 874f575645f2 (2026-09-23) was handed a feature two earlier cycles had
merged. The Dev rightly closed #286-#288 as already satisfied, the cycle
completed with no PR — and the result said nothing about why, so the E2E
harness scored "no pull request produced" and a regression. The result now
carries the numbers, and `theswarm.evals.score` reads them.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from theswarm.config import CycleConfig
from theswarm.cycle import run_daily_cycle


def _graph(state: dict) -> MagicMock:
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value={"tokens_used": 0, "cost_usd": 0.0, **state})
    return graph


async def _run(tmp_path, dev_states: list[dict]) -> dict:
    config = CycleConfig(github_repo="owner/repo", team_id="test", workspace_dir=str(tmp_path))
    github = MagicMock()
    github.ensure_branch_protection = AsyncMock()
    github.get_open_prs = AsyncMock(return_value=[])
    base_state = {
        "team_id": "test", "github_repo": "owner/repo", "github": github,
        "claude": MagicMock(), "workspace": str(tmp_path),
    }
    dev_builder = MagicMock(side_effect=[_graph(s) for s in dev_states])
    with patch("theswarm.cycle.build_po_graph", MagicMock(side_effect=lambda: _graph({}))), \
         patch("theswarm.cycle.build_techlead_graph", MagicMock(side_effect=lambda: _graph({}))), \
         patch("theswarm.cycle.build_dev_graph", dev_builder), \
         patch("theswarm.cycle.build_qa_graph", MagicMock(return_value=_graph({"demo_report": None}))), \
         patch("theswarm.cycle._ensure_workspace", new_callable=AsyncMock), \
         patch("theswarm.cycle._pull_latest", new_callable=AsyncMock), \
         patch("theswarm.cycle._build_base_state", return_value=base_state), \
         patch("theswarm.cycle_log.append_cycle_log", new_callable=AsyncMock), \
         patch("theswarm.cycle._write_cycle_learnings", new_callable=AsyncMock), \
         patch("theswarm.tools.git.cleanup_workspace", new_callable=AsyncMock):
        return await run_daily_cycle(config)


async def test_the_result_lists_every_task_closed_as_already_satisfied(tmp_path):
    result = await _run(tmp_path, [
        {"task": {"number": 286}, "pr": None, "already_satisfied": True},
        {"task": {"number": 287}, "pr": None, "already_satisfied": True},
        {"task": {"number": 288}, "pr": None, "already_satisfied": True},
        {"task": None, "pr": None},
    ])

    assert result["prs"] == []
    assert result["already_satisfied"] == [286, 287, 288]


async def test_a_task_that_produced_nothing_is_not_counted_as_satisfied(tmp_path):
    result = await _run(tmp_path, [
        {"task": {"number": 286}, "pr": None, "already_satisfied": True},
        {"task": {"number": 290}, "pr": None},
        {"task": None, "pr": None},
    ])

    assert result["already_satisfied"] == [286]


async def test_a_cycle_that_built_everything_reports_none_satisfied(tmp_path):
    result = await _run(tmp_path, [{"task": None, "pr": None}])

    assert result["already_satisfied"] == []
