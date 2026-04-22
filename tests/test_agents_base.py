"""Tests for theswarm.agents.base — shared agent helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from theswarm.agents.base import load_context, stub_result, _infer_role
from theswarm.config import Role


# ── load_context ───────────────────────────────────────────────────────


async def test_load_context_no_github():
    state = {"github": None}
    result = await load_context(state)
    assert result["context"] == "(no context — stub run)"


async def test_load_context_no_github_key():
    state = {}
    result = await load_context(state)
    assert result["context"] == "(no context — stub run)"


async def test_load_context_injects_persona_when_codename_set():
    """With a codename + phase, load_context prepends a persona line."""
    state = {
        "github": None,
        "phase": "development",
        "project_id": "demo",
        "codenames": {"dev": "Aarav"},
    }
    result = await load_context(state)
    assert "Aarav" in result["context"]
    assert "DEV" in result["context"]
    assert "demo" in result["context"]


async def test_load_context_persona_prepended_with_github():
    """Persona preamble appears before static docs when github is present."""
    mock_gh = AsyncMock()
    mock_gh.get_file_content = AsyncMock(side_effect=Exception("skip"))
    state = {
        "github": mock_gh,
        "phase": "morning",
        "project_id": "demo",
        "codenames": {"po": "Mei"},
    }
    result = await load_context(state)
    assert "Mei" in result["context"]
    assert "PO" in result["context"]


async def test_load_context_all_files():
    """Context includes static docs + structured memory."""
    mock_gh = AsyncMock()
    # get_file_content calls: GOLDEN_RULES.md, DOD.md, AGENT_MEMORY.jsonl
    mock_gh.get_file_content = AsyncMock(
        side_effect=[
            "golden rules",
            "dod content",
            '{"id":"a","category":"stack","content":"Python 3.12","confidence":1.0,"timestamp":"2026-04-07","agent":"Dev","cycle_date":"2026-04-07","supersedes":null}\n',
        ]
    )
    state = {"github": mock_gh, "phase": "development"}
    result = await load_context(state)
    assert "golden rules" in result["context"]
    assert "dod content" in result["context"]
    assert "Agent Memory" in result["context"]
    assert "Python 3.12" in result["context"]


async def test_load_context_partial_files():
    """When some static docs fail, context still includes memory."""
    mock_gh = AsyncMock()
    mock_gh.get_file_content = AsyncMock(
        side_effect=[
            "golden rules",
            Exception("not found"),  # DOD.md fails
            Exception("not found"),  # JSONL fails
            Exception("not found"),  # legacy MD fails too
        ]
    )
    state = {"github": mock_gh, "phase": "development"}
    result = await load_context(state)
    assert "golden rules" in result["context"]
    assert "not found" not in result["context"]


async def test_load_context_all_files_fail():
    """When all files fail, context includes empty memory placeholder."""
    mock_gh = AsyncMock()
    mock_gh.get_file_content = AsyncMock(side_effect=Exception("not found"))
    state = {"github": mock_gh, "phase": "development"}
    result = await load_context(state)
    # Memory section still appears with placeholder text
    assert "Agent Memory" in result["context"]
    assert "no memory entries" in result["context"]


# ── _infer_role ───────────────────────────────────────────────────────


def test_infer_role_mapping():
    assert _infer_role("morning") == "po"
    assert _infer_role("evening") == "po"
    assert _infer_role("breakdown") == "techlead"
    assert _infer_role("review_loop") == "techlead"
    assert _infer_role("development") == "dev"
    assert _infer_role("demo") == "qa"
    assert _infer_role("unknown") is None
    assert _infer_role("") is None


# ── stub_result ────────────────────────────────────────────────────────


def test_stub_result_basic():
    result = stub_result(Role.DEV, "implement")
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]
    assert "dev" in result["result"]
    assert "implement" in result["result"]


def test_stub_result_with_detail():
    result = stub_result(Role.QA, "test", detail="running e2e")
    assert "running e2e" in result["result"]
    assert "qa" in result["result"]
