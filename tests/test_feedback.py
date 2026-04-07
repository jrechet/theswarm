"""Tests for theswarm.feedback — auto-learning from human feedback."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from theswarm.feedback import (
    analyze_feedback,
    process_cycle_feedback,
    process_human_comment,
)


# ── analyze_feedback ────────────────────────────────────────────────


async def test_analyze_feedback_success():
    claude = AsyncMock()
    claude.run.return_value = AsyncMock(
        text='[{"category": "conventions", "content": "Always validate POST body", "confidence": 0.9}]',
        total_tokens=300,
        cost_usd=0.01,
    )

    lessons = await analyze_feedback(
        claude,
        pr_number=42,
        pr_title="Add login",
        decision="REQUEST_CHANGES",
        issues=[{"severity": "major", "description": "Missing input validation"}],
    )

    assert len(lessons) == 1
    assert lessons[0]["category"] == "conventions"
    assert lessons[0]["confidence"] == 0.9


async def test_analyze_feedback_empty():
    claude = AsyncMock()
    claude.run.return_value = AsyncMock(text="[]", total_tokens=100, cost_usd=0.001)

    lessons = await analyze_feedback(
        claude, pr_number=1, pr_title="Fix", decision="APPROVE", issues=[],
    )
    assert lessons == []


async def test_analyze_feedback_parse_failure():
    claude = AsyncMock()
    claude.run.return_value = AsyncMock(text="not json", total_tokens=100, cost_usd=0.001)

    lessons = await analyze_feedback(
        claude, pr_number=1, pr_title="Fix", decision="APPROVE", issues=[],
    )
    assert lessons == []


async def test_analyze_feedback_with_markdown_fences():
    claude = AsyncMock()
    claude.run.return_value = AsyncMock(
        text='```json\n[{"category": "errors", "content": "Check null", "confidence": 0.8}]\n```',
        total_tokens=200,
        cost_usd=0.005,
    )

    lessons = await analyze_feedback(
        claude, pr_number=1, pr_title="Fix", decision="REQUEST_CHANGES",
        issues=[{"severity": "critical", "description": "NullPointerException"}],
    )
    assert len(lessons) == 1
    assert lessons[0]["content"] == "Check null"


async def test_analyze_feedback_invalid_category():
    claude = AsyncMock()
    claude.run.return_value = AsyncMock(
        text='[{"category": "banana", "content": "Some lesson", "confidence": 0.7}]',
        total_tokens=100,
        cost_usd=0.001,
    )

    lessons = await analyze_feedback(
        claude, pr_number=1, pr_title="Fix", decision="REQUEST_CHANGES", issues=[],
    )
    assert lessons[0]["category"] == "learnings"  # falls back


async def test_analyze_feedback_caps_confidence():
    claude = AsyncMock()
    claude.run.return_value = AsyncMock(
        text='[{"category": "errors", "content": "Lesson", "confidence": 1.5}]',
        total_tokens=100,
        cost_usd=0.001,
    )

    lessons = await analyze_feedback(
        claude, pr_number=1, pr_title="Fix", decision="REQUEST_CHANGES", issues=[],
    )
    assert lessons[0]["confidence"] == 1.0


# ── process_cycle_feedback ──────────────────────────────────────────


async def test_process_cycle_feedback_with_rejections():
    github = AsyncMock()
    github.get_file_content.side_effect = Exception("Not found")

    claude = AsyncMock()
    claude.run.return_value = AsyncMock(
        text='[{"category": "errors", "content": "Always handle errors", "confidence": 0.85}]',
        total_tokens=300,
        cost_usd=0.01,
    )

    cycle_result = {
        "date": "2026-04-07",
        "reviews": [{
            "pr_number": 1,
            "pr_title": "Add feature",
            "decision": "REQUEST_CHANGES",
            "issues": [{"severity": "major", "description": "Missing error handling"}],
        }],
        "demo_report": {"quality_gates": {}},
    }

    entries = await process_cycle_feedback(github, claude, cycle_result)
    assert len(entries) >= 1
    assert entries[0]["agent"] == "feedback"


async def test_process_cycle_feedback_no_rejections():
    github = AsyncMock()
    github.get_file_content.side_effect = Exception("Not found")

    claude = AsyncMock()

    cycle_result = {
        "date": "2026-04-07",
        "reviews": [{"pr_number": 1, "decision": "APPROVE"}],
        "demo_report": {"quality_gates": {}},
    }

    entries = await process_cycle_feedback(github, claude, cycle_result)
    # No rejections, no feedback entries (except possibly quality gate failures)
    assert len(entries) == 0
    claude.run.assert_not_called()


async def test_process_cycle_feedback_quality_gate_failure():
    github = AsyncMock()
    github.get_file_content.side_effect = Exception("Not found")

    claude = AsyncMock()

    cycle_result = {
        "date": "2026-04-07",
        "reviews": [],
        "demo_report": {
            "quality_gates": {
                "unit_tests": {"status": "fail", "passed": 48, "failed": 2},
                "security": {"status": "pass"},
            },
        },
    }

    entries = await process_cycle_feedback(github, claude, cycle_result)
    assert len(entries) == 1
    assert "unit_tests" in entries[0]["content"]
    assert entries[0]["category"] == "errors"


# ── process_human_comment ───────────────────────────────────────────


async def test_process_human_comment():
    github = AsyncMock()
    github.get_file_content.side_effect = Exception("Not found")

    claude = AsyncMock()
    claude.run.return_value = AsyncMock(
        text='[{"category": "conventions", "content": "Use blue for primary buttons", "confidence": 0.85}]',
        total_tokens=200,
        cost_usd=0.005,
    )

    entries = await process_human_comment(
        claude, github, pr_number=42, comment="The header color is too dark",
    )
    assert len(entries) == 1
    assert entries[0]["agent"] == "feedback"
    assert entries[0]["confidence"] == 0.85


async def test_process_human_comment_no_lessons():
    github = AsyncMock()
    github.get_file_content.side_effect = Exception("Not found")

    claude = AsyncMock()
    claude.run.return_value = AsyncMock(text="[]", total_tokens=100, cost_usd=0.001)

    entries = await process_human_comment(
        claude, github, pr_number=42, comment="Looks good",
    )
    assert entries == []
