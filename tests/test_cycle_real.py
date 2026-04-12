"""Tests for cycle.py real-mode paths — run_daily_cycle, run_dev_only, run_techlead_only."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theswarm.config import CycleConfig, Role
from theswarm.cycle import BudgetExceeded, run_daily_cycle, run_dev_only, run_techlead_only


# ── Helpers ───────────────────────────────────────────────────────────────


def _mock_graph(return_state: dict | None = None) -> MagicMock:
    """Create a mock compiled graph whose ainvoke returns the given state."""
    if return_state is None:
        return_state = {"tokens_used": 100, "cost_usd": 0.01}
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value=return_state)
    return graph


def _real_config(tmp_path) -> CycleConfig:
    """Create a CycleConfig that is in real mode but uses a temp workspace."""
    return CycleConfig(
        github_repo="owner/repo",
        team_id="test",
        workspace_dir=str(tmp_path),
    )


# Patches common to all full-cycle tests
_CYCLE_PATCHES = [
    "theswarm.cycle.build_po_graph",
    "theswarm.cycle.build_techlead_graph",
    "theswarm.cycle.build_dev_graph",
    "theswarm.cycle.build_qa_graph",
    "theswarm.cycle._ensure_workspace",
    "theswarm.cycle._pull_latest",
    "theswarm.cycle._build_base_state",
    "theswarm.cycle.append_cycle_log",
    "theswarm.cycle._write_cycle_learnings",
]


# ── run_daily_cycle (real mode) ──────────────────────────────────────────


async def test_run_daily_cycle_real_mode(tmp_path):
    """Full cycle with mocked graphs completes and returns expected keys."""
    config = _real_config(tmp_path)

    po_state = {"tokens_used": 100, "cost_usd": 0.01, "daily_plan": "plan"}
    tl_breakdown_state = {"tokens_used": 200, "cost_usd": 0.02}
    # Dev returns no task on first iteration to end the loop
    dev_state = {"tokens_used": 50, "cost_usd": 0.005, "task": None, "pr": None}
    qa_state = {
        "tokens_used": 80, "cost_usd": 0.008,
        "demo_report": {"overall_status": "green", "date": "2025-01-01"},
    }
    po_evening_state = {"tokens_used": 60, "cost_usd": 0.006, "daily_report": "All good"}

    po_graph = _mock_graph(po_state)
    tl_graph = _mock_graph(tl_breakdown_state)
    dev_graph = _mock_graph(dev_state)
    qa_graph = _mock_graph(qa_state)

    # PO is called twice (morning + evening), so we need side_effect
    po_builder = MagicMock(side_effect=[
        _mock_graph(po_state),
        _mock_graph(po_evening_state),
    ])
    tl_builder = MagicMock(return_value=tl_graph)
    dev_builder = MagicMock(return_value=dev_graph)
    qa_builder = MagicMock(return_value=qa_graph)

    mock_github = MagicMock()
    mock_github.ensure_branch_protection = AsyncMock()
    mock_github.get_open_prs = AsyncMock(return_value=[])
    base_state = {
        "team_id": "test",
        "github_repo": "owner/repo",
        "github": mock_github,
        "claude": MagicMock(),
        "workspace": str(tmp_path),
    }

    with patch("theswarm.cycle.build_po_graph", po_builder), \
         patch("theswarm.cycle.build_techlead_graph", tl_builder), \
         patch("theswarm.cycle.build_dev_graph", dev_builder), \
         patch("theswarm.cycle.build_qa_graph", qa_builder), \
         patch("theswarm.cycle._ensure_workspace", new_callable=AsyncMock), \
         patch("theswarm.cycle._pull_latest", new_callable=AsyncMock), \
         patch("theswarm.cycle._build_base_state", return_value=base_state), \
         patch("theswarm.cycle_log.append_cycle_log", new_callable=AsyncMock), \
         patch("theswarm.cycle._write_cycle_learnings", new_callable=AsyncMock), \
         patch("theswarm.tools.git.cleanup_workspace", new_callable=AsyncMock):
        result = await run_daily_cycle(config)

    assert "date" in result
    assert "tokens" in result
    assert "cost_usd" in result
    assert "demo_report" in result
    assert result["demo_report"]["overall_status"] == "green"
    assert result["daily_report"] == "All good"


async def test_run_daily_cycle_with_progress_callback(tmp_path):
    """Verify on_progress callback is called during the cycle."""
    config = _real_config(tmp_path)

    # Dev returns no task immediately to end dev loop
    dev_state = {"tokens_used": 0, "cost_usd": 0.0, "task": None, "pr": None}
    stub_state = {"tokens_used": 0, "cost_usd": 0.0}
    qa_state = {
        "tokens_used": 0, "cost_usd": 0.0,
        "demo_report": {"overall_status": "red", "date": "2025-01-01"},
    }

    mock_github = MagicMock()
    mock_github.ensure_branch_protection = AsyncMock()
    mock_github.get_open_prs = AsyncMock(return_value=[])
    base_state = {
        "team_id": "test",
        "github_repo": "owner/repo",
        "github": mock_github,
        "claude": MagicMock(),
        "workspace": str(tmp_path),
    }

    progress_calls = []

    async def track_progress(role: str, message: str) -> None:
        progress_calls.append((role, message))

    with patch("theswarm.cycle.build_po_graph", MagicMock(return_value=_mock_graph(stub_state))), \
         patch("theswarm.cycle.build_techlead_graph", MagicMock(return_value=_mock_graph(stub_state))), \
         patch("theswarm.cycle.build_dev_graph", MagicMock(return_value=_mock_graph(dev_state))), \
         patch("theswarm.cycle.build_qa_graph", MagicMock(return_value=_mock_graph(qa_state))), \
         patch("theswarm.cycle._ensure_workspace", new_callable=AsyncMock), \
         patch("theswarm.cycle._pull_latest", new_callable=AsyncMock), \
         patch("theswarm.cycle._build_base_state", return_value=base_state), \
         patch("theswarm.cycle_log.append_cycle_log", new_callable=AsyncMock), \
         patch("theswarm.cycle._write_cycle_learnings", new_callable=AsyncMock), \
         patch("theswarm.tools.git.cleanup_workspace", new_callable=AsyncMock):
        await run_daily_cycle(config, on_progress=track_progress)

    assert len(progress_calls) > 0
    roles_seen = {call[0] for call in progress_calls}
    assert "PO" in roles_seen
    assert "Dev" in roles_seen
    assert "QA" in roles_seen


async def test_budget_exceeded(tmp_path):
    """When a graph returns tokens exceeding the budget, BudgetExceeded is raised."""
    config = CycleConfig(
        github_repo="owner/repo",
        team_id="test",
        workspace_dir=str(tmp_path),
        token_budget={
            Role.PO: 50,  # Very low budget
            Role.TECHLEAD: 1_000_000,
            Role.DEV: 1_000_000,
            Role.QA: 1_000_000,
        },
    )

    # PO returns more tokens than the budget
    po_state = {"tokens_used": 100, "cost_usd": 0.01}

    mock_github = MagicMock()
    mock_github.ensure_branch_protection = AsyncMock()
    mock_github.get_open_prs = AsyncMock(return_value=[])
    base_state = {
        "team_id": "test",
        "github_repo": "owner/repo",
        "github": mock_github,
        "claude": MagicMock(),
        "workspace": str(tmp_path),
    }

    with patch("theswarm.cycle.build_po_graph", MagicMock(return_value=_mock_graph(po_state))), \
         patch("theswarm.cycle._ensure_workspace", new_callable=AsyncMock), \
         patch("theswarm.cycle._build_base_state", return_value=base_state), \
         pytest.raises(BudgetExceeded) as exc_info:
        await run_daily_cycle(config)

    assert exc_info.value.role == "po"
    assert exc_info.value.used == 100
    assert exc_info.value.budget == 50


# ── run_dev_only ─────────────────────────────────────────────────────────


async def test_run_dev_only(tmp_path):
    """run_dev_only calls only the dev graph and returns its result."""
    config = _real_config(tmp_path)

    dev_state = {
        "tokens_used": 500, "cost_usd": 0.05,
        "pr": {"number": 42, "url": "https://github.com/owner/repo/pull/42"},
    }

    with patch("theswarm.cycle.build_dev_graph", MagicMock(return_value=_mock_graph(dev_state))), \
         patch("theswarm.cycle._ensure_workspace", new_callable=AsyncMock), \
         patch("theswarm.cycle._build_base_state", return_value={
             "team_id": "test", "github_repo": "owner/repo",
             "github": None, "claude": None, "workspace": str(tmp_path),
         }):
        result = await run_dev_only(config)

    assert result["pr"]["number"] == 42
    assert result["tokens"] == 500
    assert result["cost_usd"] == 0.05


async def test_run_dev_only_no_pr(tmp_path):
    """run_dev_only with no PR produced."""
    config = _real_config(tmp_path)

    dev_state = {"tokens_used": 200, "cost_usd": 0.02, "pr": None}

    with patch("theswarm.cycle.build_dev_graph", MagicMock(return_value=_mock_graph(dev_state))), \
         patch("theswarm.cycle._ensure_workspace", new_callable=AsyncMock), \
         patch("theswarm.cycle._build_base_state", return_value={
             "team_id": "test", "github_repo": "owner/repo",
             "github": None, "claude": None, "workspace": str(tmp_path),
         }):
        result = await run_dev_only(config)

    assert result["pr"] is None
    assert result["tokens"] == 200


# ── run_techlead_only ────────────────────────────────────────────────────


async def test_run_techlead_only(tmp_path):
    """run_techlead_only calls only the techlead graph in review mode."""
    config = _real_config(tmp_path)

    tl_state = {
        "tokens_used": 300, "cost_usd": 0.03,
        "reviews": [
            {"pr_number": 10, "decision": "APPROVE", "summary": "Looks good"},
            {"pr_number": 11, "decision": "REQUEST_CHANGES", "summary": "Needs work"},
        ],
    }

    with patch("theswarm.cycle.build_techlead_graph", MagicMock(return_value=_mock_graph(tl_state))), \
         patch("theswarm.cycle._ensure_workspace", new_callable=AsyncMock), \
         patch("theswarm.cycle._build_base_state", return_value={
             "team_id": "test", "github_repo": "owner/repo",
             "github": None, "claude": None, "workspace": str(tmp_path),
         }):
        result = await run_techlead_only(config)

    assert len(result["reviews"]) == 2
    assert result["tokens"] == 300
    assert result["cost_usd"] == 0.03
    assert result["reviews"][0]["decision"] == "APPROVE"


async def test_run_techlead_only_no_reviews(tmp_path):
    """run_techlead_only with no open PRs returns empty reviews."""
    config = _real_config(tmp_path)

    tl_state = {"tokens_used": 50, "cost_usd": 0.005, "reviews": []}

    with patch("theswarm.cycle.build_techlead_graph", MagicMock(return_value=_mock_graph(tl_state))), \
         patch("theswarm.cycle._ensure_workspace", new_callable=AsyncMock), \
         patch("theswarm.cycle._build_base_state", return_value={
             "team_id": "test", "github_repo": "owner/repo",
             "github": None, "claude": None, "workspace": str(tmp_path),
         }):
        result = await run_techlead_only(config)

    assert result["reviews"] == []
    assert result["tokens"] == 50
