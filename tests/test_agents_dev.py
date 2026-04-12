"""Tests for the Dev agent (src/theswarm/agents/dev.py)."""

from __future__ import annotations

import pytest

from theswarm.agents.dev import (
    _extract_us_id,
    _make_branch_name,
    _should_open_pr,
    _should_skip,
    build_dev_graph,
    implement_task,
    open_pull_request,
    pick_task,
    run_quality_gates,
)


# ── build_dev_graph ────────────────────────────────────────────────────


def test_build_dev_graph_returns_compiled_graph():
    graph = build_dev_graph()
    # A compiled graph has an `ainvoke` method
    assert callable(getattr(graph, "ainvoke", None))


async def test_stub_mode_returns_stub_result():
    graph = build_dev_graph()
    result = await graph.ainvoke({"phase": "development"})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result.get("result", "")


# ── _make_branch_name ──────────────────────────────────────────────────


def test_make_branch_name_with_us_prefix():
    task = {"number": 1, "title": "US-001: User registration"}
    name = _make_branch_name(task)
    assert name.startswith("feat/us-001-")
    assert "user-registration" in name


def test_make_branch_name_without_us_prefix():
    task = {"number": 42, "title": "Fix login button color"}
    name = _make_branch_name(task)
    assert name.startswith("feat/issue-42-")
    assert "fix-login-button" in name


def test_make_branch_name_long_title():
    task = {"number": 5, "title": "US-010: " + "a" * 100}
    name = _make_branch_name(task)
    # Branch name slug is capped at 40 chars
    slug_part = name.split("us-010-")[1]
    assert len(slug_part) <= 40


# ── _extract_us_id ─────────────────────────────────────────────────────


def test_extract_us_id_with_us_prefix():
    task = {"number": 1, "title": "US-001: User registration"}
    assert _extract_us_id(task) == "US-001"


def test_extract_us_id_fallback_to_issue_number():
    task = {"number": 42, "title": "Fix login button color"}
    assert _extract_us_id(task) == "#42"


# ── _should_skip ───────────────────────────────────────────────────────


def test_should_skip_when_task_is_none():
    state = {"task": None}
    assert _should_skip(state) == "end"


def test_should_skip_when_task_exists():
    state = {"task": {"number": 1, "title": "Something"}}
    assert _should_skip(state) == "implement"


# ── _should_open_pr ────────────────────────────────────────────────────


def test_should_open_pr_when_branch_is_none():
    state = {"branch": None}
    assert _should_open_pr(state) == "end"


def test_should_open_pr_when_branch_exists():
    state = {"branch": "feat/us-001-thing"}
    assert _should_open_pr(state) == "open_pr"


# ── pick_task (stub) ──────────────────────────────────────────────────


async def test_pick_task_stub_mode():
    result = await pick_task({"phase": "development"})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]


# ── implement_task (stub) ─────────────────────────────────────────────


async def test_implement_task_stub_no_task():
    result = await implement_task({"phase": "development"})
    assert result["tokens_used"] == 0
    assert result["result"] == "no task"


async def test_implement_task_stub_with_task():
    state = {
        "task": {"number": 1, "title": "Add login", "body": ""},
        "claude": None,
        "workspace": None,
    }
    result = await implement_task(state)
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]


# ── run_quality_gates (stub) ──────────────────────────────────────────


async def test_run_quality_gates_stub():
    state = {"task": None, "workspace": None, "claude": None}
    result = await run_quality_gates(state)
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]


# ── open_pull_request (stub) ──────────────────────────────────────────


async def test_open_pull_request_stub():
    state = {
        "task": None,
        "branch": None,
        "github": None,
        "workspace": None,
    }
    result = await open_pull_request(state)
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]
