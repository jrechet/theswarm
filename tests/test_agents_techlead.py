"""Tests for the TechLead agent (src/theswarm/agents/techlead.py)."""

from __future__ import annotations

import pytest

from theswarm.agents.techlead import (
    _format_files_diff,
    _format_review_body,
    _parse_review_json,
    _parse_tasks_json,
    _route_phase,
    breakdown_stories,
    build_techlead_graph,
    merge_approved_prs,
    poll_and_review_prs,
)


# ── build_techlead_graph ───────────────────────────────────────────────


def test_build_techlead_graph_returns_compiled_graph():
    graph = build_techlead_graph()
    assert callable(getattr(graph, "ainvoke", None))


# ── stub mode: breakdown ──────────────────────────────────────────────


async def test_stub_mode_breakdown():
    graph = build_techlead_graph()
    result = await graph.ainvoke({"phase": "breakdown"})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result.get("result", "")


# ── stub mode: review_loop ────────────────────────────────────────────


async def test_stub_mode_review_loop():
    graph = build_techlead_graph()
    result = await graph.ainvoke({"phase": "review_loop"})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result.get("result", "")


# ── _route_phase ───────────────────────────────────────────────────────


def test_route_phase_review_loop():
    assert _route_phase({"phase": "review_loop"}) == "poll_and_review_prs"


def test_route_phase_breakdown():
    assert _route_phase({"phase": "breakdown"}) == "breakdown_stories"


def test_route_phase_default():
    assert _route_phase({}) == "breakdown_stories"


# ── _parse_tasks_json ──────────────────────────────────────────────────


def test_parse_tasks_json_valid_array():
    text = '[{"title": "Task 1", "body": "Do stuff", "labels": ["role:dev"]}]'
    result = _parse_tasks_json(text)
    assert len(result) == 1
    assert result[0]["title"] == "Task 1"


def test_parse_tasks_json_markdown_fenced():
    text = '```json\n[{"title": "Task 1"}]\n```'
    result = _parse_tasks_json(text)
    assert len(result) == 1
    assert result[0]["title"] == "Task 1"


def test_parse_tasks_json_embedded_in_text():
    text = 'Here are the tasks:\n[{"title": "T1"}, {"title": "T2"}]\nDone!'
    result = _parse_tasks_json(text)
    assert len(result) == 2


def test_parse_tasks_json_invalid():
    text = "This is not JSON at all"
    result = _parse_tasks_json(text)
    assert result == []


# ── _parse_review_json ─────────────────────────────────────────────────


def test_parse_review_json_valid():
    text = '{"decision": "APPROVE", "summary": "Looks good", "issues": []}'
    result = _parse_review_json(text)
    assert result["decision"] == "APPROVE"
    assert result["summary"] == "Looks good"


def test_parse_review_json_markdown_fenced():
    text = '```json\n{"decision": "REQUEST_CHANGES", "summary": "Needs work", "issues": []}\n```'
    result = _parse_review_json(text)
    assert result["decision"] == "REQUEST_CHANGES"


def test_parse_review_json_invalid_fallback():
    text = "Not valid JSON here"
    result = _parse_review_json(text)
    assert result["decision"] == "COMMENT"
    assert "Not valid JSON" in result["summary"]


# ── _format_files_diff ─────────────────────────────────────────────────


def test_format_files_diff_with_patch():
    files = [
        {
            "filename": "src/main.py",
            "status": "modified",
            "additions": 5,
            "deletions": 2,
            "patch": "@@ -1,3 +1,6 @@\n+new line",
        }
    ]
    result = _format_files_diff(files)
    assert "src/main.py" in result
    assert "```diff" in result
    assert "+new line" in result


def test_format_files_diff_without_patch():
    files = [
        {
            "filename": "image.png",
            "status": "added",
            "additions": 0,
            "deletions": 0,
            "patch": None,
        }
    ]
    result = _format_files_diff(files)
    assert "image.png" in result
    assert "no diff available" in result


# ── _format_review_body ────────────────────────────────────────────────


def test_format_review_body_with_issues():
    issues = [
        {"severity": "critical", "file": "src/auth.py", "description": "SQL injection risk"},
        {"severity": "nit", "file": "", "description": "Rename variable"},
    ]
    body = _format_review_body("Needs work", issues)
    assert "Needs work" in body
    assert "CRITICAL" in body
    assert "src/auth.py" in body
    assert "NIT" in body


def test_format_review_body_no_issues():
    body = _format_review_body("All good", [])
    assert "All good" in body
    assert "No issues found" in body


# ── breakdown_stories (stub) ──────────────────────────────────────────


async def test_breakdown_stories_stub():
    result = await breakdown_stories({"github": None, "claude": None})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]


# ── poll_and_review_prs (stub) ────────────────────────────────────────


async def test_poll_and_review_prs_stub():
    result = await poll_and_review_prs({"github": None, "claude": None})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]


# ── merge_approved_prs (stub) ─────────────────────────────────────────


async def test_merge_approved_prs_stub():
    result = await merge_approved_prs({"github": None, "reviews": []})
    assert result["tokens_used"] == 0
    assert "[STUB]" in result["result"]
