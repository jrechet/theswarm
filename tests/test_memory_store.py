"""Tests for theswarm.memory_store — structured JSONL memory."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from theswarm.memory_store import (
    CATEGORIES,
    MEMORY_JSONL_PATH,
    ROLE_CATEGORIES,
    _entries_to_jsonl,
    _migrate_legacy_md,
    _parse_jsonl,
    append_entries,
    compact_memory,
    format_for_prompt,
    load_entries,
    make_entry,
    query,
    run_retrospective,
    save_entries,
)


# ── make_entry ──────────────────────────────────────────────────────


def test_make_entry_basic():
    e = make_entry("stack", "Python 3.12", "Dev")
    assert e["category"] == "stack"
    assert e["content"] == "Python 3.12"
    assert e["agent"] == "Dev"
    assert e["confidence"] == 1.0
    assert len(e["id"]) == 12
    assert e["timestamp"]


def test_make_entry_with_overrides():
    e = make_entry("errors", "Don't do X", "QA", confidence=0.5, cycle_date="2026-04-07", supersedes="abc123")
    assert e["confidence"] == 0.5
    assert e["cycle_date"] == "2026-04-07"
    assert e["supersedes"] == "abc123"


# ── JSONL parsing ───────────────────────────────────────────────────


def test_parse_jsonl_valid():
    raw = '{"id":"a","content":"hello"}\n{"id":"b","content":"world"}\n'
    entries = _parse_jsonl(raw)
    assert len(entries) == 2
    assert entries[0]["content"] == "hello"


def test_parse_jsonl_empty():
    assert _parse_jsonl("") == []
    assert _parse_jsonl("\n\n") == []


def test_parse_jsonl_malformed_line():
    raw = '{"id":"a"}\nnot json\n{"id":"b"}\n'
    entries = _parse_jsonl(raw)
    assert len(entries) == 2  # skips bad line


def test_entries_to_jsonl():
    entries = [{"id": "a", "content": "x"}, {"id": "b", "content": "y"}]
    result = _entries_to_jsonl(entries)
    lines = result.strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["id"] == "a"


# ── Legacy migration ───────────────────────────────────────────────


def test_migrate_legacy_md_basic():
    md = """\
# Agent Memory — myrepo

## Stack technique
- [2026-04-06] (QA) Code coverage: 80%

## Conventions de code
_(populated by agents)_

## Erreurs à éviter
- [2026-04-06] (TechLead) PR #5: Missing null check

## Décisions architecturales
- [2026-04-06] (Dev) Use FastAPI for REST endpoints
"""
    entries = _migrate_legacy_md(md)
    assert len(entries) == 3
    categories = {e["category"] for e in entries}
    assert "stack" in categories
    assert "errors" in categories
    assert "architecture" in categories


def test_migrate_legacy_md_empty():
    assert _migrate_legacy_md("") == []
    assert _migrate_legacy_md("# Just a title") == []


def test_migrate_legacy_md_confidence():
    md = "## Stack technique\n- [2026-04-06] (QA) Something"
    entries = _migrate_legacy_md(md)
    assert entries[0]["confidence"] == 0.7  # legacy gets lower confidence


# ── load_entries ────────────────────────────────────────────────────


async def test_load_entries_jsonl():
    github = AsyncMock()
    entry = make_entry("stack", "Python 3.12", "Dev")
    github.get_file_content.return_value = json.dumps(entry) + "\n"

    entries = await load_entries(github)
    assert len(entries) == 1
    assert entries[0]["content"] == "Python 3.12"
    github.get_file_content.assert_called_once_with(MEMORY_JSONL_PATH, ref="main")


async def test_load_entries_fallback_to_legacy():
    github = AsyncMock()
    # JSONL not found
    github.get_file_content.side_effect = [
        Exception("Not found"),
        "## Stack technique\n- [2026-04-06] (Dev) Use pytest\n",
    ]

    entries = await load_entries(github)
    assert len(entries) == 1
    assert "pytest" in entries[0]["content"]


async def test_load_entries_nothing():
    github = AsyncMock()
    github.get_file_content.side_effect = Exception("Not found")

    entries = await load_entries(github)
    assert entries == []


# ── save_entries ────────────────────────────────────────────────────


async def test_save_entries():
    github = AsyncMock()
    entries = [make_entry("stack", "test", "Dev")]

    result = await save_entries(github, entries)
    assert result is True
    github.update_file.assert_called_once()
    call_args = github.update_file.call_args
    assert call_args[0][0] == MEMORY_JSONL_PATH


async def test_save_entries_failure():
    github = AsyncMock()
    github.update_file.side_effect = Exception("API error")

    result = await save_entries(github, [make_entry("stack", "x", "Dev")])
    assert result is False


# ── append_entries ──────────────────────────────────────────────────


async def test_append_entries():
    github = AsyncMock()
    existing = make_entry("stack", "existing", "Dev")
    github.get_file_content.return_value = json.dumps(existing) + "\n"

    new = [make_entry("errors", "new learning", "QA")]
    result = await append_entries(github, new)

    assert result is True
    written = github.update_file.call_args[0][1]
    lines = written.strip().split("\n")
    assert len(lines) == 2  # existing + new


async def test_append_entries_empty():
    github = AsyncMock()
    result = await append_entries(github, [])
    assert result is True
    github.update_file.assert_not_called()


# ── query ───────────────────────────────────────────────────────────


def _sample_entries():
    return [
        make_entry("stack", "Python 3.12 required", "Dev", confidence=0.9),
        make_entry("conventions", "Use snake_case for functions", "TechLead", confidence=0.95),
        make_entry("errors", "Never hardcode API keys", "QA", confidence=1.0),
        make_entry("architecture", "FastAPI for REST", "Dev", confidence=0.8),
        make_entry("learnings", "Coverage improves with integration tests", "retrospective", confidence=0.6),
        make_entry("errors", "Old stale entry", "Dev", confidence=0.2),
    ]


def test_query_by_role_dev():
    entries = _sample_entries()
    results = query(entries, role="dev")
    categories = {r["category"] for r in results}
    # Dev gets: conventions, stack, errors
    assert "conventions" in categories
    assert "stack" in categories
    assert "errors" in categories
    assert "architecture" not in categories


def test_query_by_role_techlead():
    entries = _sample_entries()
    results = query(entries, role="techlead")
    categories = {r["category"] for r in results}
    assert "conventions" in categories
    assert "architecture" in categories
    assert "errors" in categories


def test_query_by_categories():
    entries = _sample_entries()
    results = query(entries, categories=["stack"])
    assert all(r["category"] == "stack" for r in results)


def test_query_by_keywords():
    entries = _sample_entries()
    results = query(entries, keywords=["python"])
    assert len(results) == 1
    assert "Python" in results[0]["content"]


def test_query_min_confidence():
    entries = _sample_entries()
    # Default min_confidence=0.3 should filter the 0.2 entry
    results = query(entries)
    assert not any(r["content"] == "Old stale entry" for r in results)


def test_query_limit():
    entries = _sample_entries()
    results = query(entries, limit=2)
    assert len(results) == 2


def test_query_empty():
    assert query([]) == []


# ── format_for_prompt ───────────────────────────────────────────────


def test_format_for_prompt_basic():
    entries = _sample_entries()
    text = format_for_prompt(entries)
    assert "Stack & Tools" in text
    assert "Python 3.12" in text
    assert "Known Pitfalls" in text


def test_format_for_prompt_empty():
    assert format_for_prompt([]) == "(no memory entries)"


def test_format_for_prompt_max_chars():
    entries = [make_entry("stack", "x" * 200, "Dev") for _ in range(50)]
    text = format_for_prompt(entries, max_chars=500)
    assert len(text) < 700  # some overhead for headings


# ── run_retrospective ───────────────────────────────────────────────


async def test_retrospective_success():
    github = AsyncMock()
    github.get_file_content.side_effect = Exception("Not found")

    claude = AsyncMock()
    claude.run.return_value = AsyncMock(
        text='[{"category": "errors", "content": "Always validate input", "confidence": 0.9}]',
        total_tokens=500,
        cost_usd=0.01,
    )

    cycle_result = {
        "date": "2026-04-07",
        "cost_usd": 2.50,
        "prs": [{"number": 1}],
        "reviews": [{"pr_number": 1, "decision": "APPROVE"}],
        "demo_report": {"quality_gates": {}},
    }

    entries = await run_retrospective(github, claude, cycle_result)
    assert len(entries) == 1
    assert entries[0]["category"] == "errors"
    assert entries[0]["agent"] == "retrospective"
    assert entries[0]["content"] == "Always validate input"


async def test_retrospective_empty():
    github = AsyncMock()
    github.get_file_content.side_effect = Exception("Not found")

    claude = AsyncMock()
    claude.run.return_value = AsyncMock(text="[]", total_tokens=100, cost_usd=0.001)

    entries = await run_retrospective(github, claude, {"date": "2026-04-07"})
    assert entries == []


async def test_retrospective_parse_failure():
    github = AsyncMock()
    github.get_file_content.side_effect = Exception("Not found")

    claude = AsyncMock()
    claude.run.return_value = AsyncMock(text="not json at all", total_tokens=100, cost_usd=0.001)

    entries = await run_retrospective(github, claude, {"date": "2026-04-07"})
    assert entries == []


async def test_retrospective_with_markdown_fences():
    github = AsyncMock()
    github.get_file_content.side_effect = Exception("Not found")

    claude = AsyncMock()
    claude.run.return_value = AsyncMock(
        text='```json\n[{"category": "stack", "content": "Use ruff", "confidence": 0.8}]\n```',
        total_tokens=200,
        cost_usd=0.005,
    )

    entries = await run_retrospective(github, claude, {"date": "2026-04-07"})
    assert len(entries) == 1
    assert entries[0]["content"] == "Use ruff"


async def test_retrospective_with_review_issues():
    github = AsyncMock()
    github.get_file_content.side_effect = Exception("Not found")

    claude = AsyncMock()
    claude.run.return_value = AsyncMock(
        text='[{"category": "errors", "content": "Missing null check in API handler", "confidence": 0.9}]',
        total_tokens=300,
        cost_usd=0.01,
    )

    cycle_result = {
        "date": "2026-04-07",
        "cost_usd": 3.0,
        "prs": [{"number": 1}],
        "reviews": [{
            "pr_number": 1,
            "decision": "REQUEST_CHANGES",
            "issues": [{"description": "Missing null check on response.data"}],
        }],
        "demo_report": None,
    }

    entries = await run_retrospective(github, claude, cycle_result)
    assert len(entries) == 1
    # Verify the prompt included review issues
    prompt_arg = claude.run.call_args[0][0]
    assert "Missing null check" in prompt_arg


# ── compact_memory ──────────────────────────────────────────────────


async def test_compact_below_threshold():
    github = AsyncMock()
    github.get_file_content.return_value = _entries_to_jsonl(
        [make_entry("stack", f"entry {i}", "Dev") for i in range(10)]
    )

    claude = AsyncMock()
    result = await compact_memory(github, claude, threshold=50)
    assert result is False  # not needed
    claude.run.assert_not_called()


async def test_compact_success():
    github = AsyncMock()
    entries = [make_entry("stack", f"entry {i}", "Dev") for i in range(60)]
    github.get_file_content.return_value = _entries_to_jsonl(entries)

    claude = AsyncMock()
    claude.run.return_value = AsyncMock(
        text='[{"category": "stack", "content": "Merged summary", "confidence": 0.9}]',
        total_tokens=500,
        cost_usd=0.02,
    )

    result = await compact_memory(github, claude, threshold=50)
    assert result is True
    # Should have saved compacted entries
    github.update_file.assert_called_once()
    written = github.update_file.call_args[0][1]
    assert "Merged summary" in written


async def test_compact_failure():
    github = AsyncMock()
    entries = [make_entry("stack", f"entry {i}", "Dev") for i in range(60)]
    github.get_file_content.return_value = _entries_to_jsonl(entries)

    claude = AsyncMock()
    claude.run.return_value = AsyncMock(text="not json", total_tokens=100, cost_usd=0.01)

    result = await compact_memory(github, claude, threshold=50)
    assert result is False


async def test_compact_empty_result():
    github = AsyncMock()
    entries = [make_entry("stack", f"entry {i}", "Dev") for i in range(60)]
    github.get_file_content.return_value = _entries_to_jsonl(entries)

    claude = AsyncMock()
    claude.run.return_value = AsyncMock(text="[]", total_tokens=100, cost_usd=0.01)

    result = await compact_memory(github, claude, threshold=50)
    assert result is False  # empty compaction rejected


# ── base.py integration ─────────────────────────────────────────────


async def test_load_context_uses_memory_store():
    """Verify base.load_context loads structured memory."""
    from unittest.mock import patch

    github = AsyncMock()
    # GOLDEN_RULES.md and DOD.md
    github.get_file_content.side_effect = [
        "# Golden Rules\nRule 1",
        "# DoD\nDone when tested",
        # JSONL for memory_store
        _entries_to_jsonl([make_entry("conventions", "Use snake_case", "TechLead")]),
    ]

    from theswarm.agents.base import load_context
    state = {"github": github, "phase": "development"}
    result = await load_context(state)

    context = result["context"]
    assert "Golden Rules" in context
    assert "Agent Memory" in context
    assert "snake_case" in context


async def test_load_context_stub_mode():
    from theswarm.agents.base import load_context
    state = {"github": None, "phase": "development"}
    result = await load_context(state)
    assert "stub" in result["context"].lower() or "no context" in result["context"].lower()
