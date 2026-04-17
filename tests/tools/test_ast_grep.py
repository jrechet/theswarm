"""Tests for theswarm.tools.ast_grep — AST-Grep wrapper."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from theswarm.tools.ast_grep import (
    AstGrepMatch,
    _parse_matches,
    check_patterns,
    is_available,
    search,
)


# ── Unit tests for _parse_matches ─────────────────────────────────


class TestParseMatches:
    def test_parses_valid_json(self) -> None:
        raw = json.dumps([
            {
                "file": "src/main.py",
                "text": "def hello():",
                "range": {"start": {"line": 10, "column": 0}},
            },
        ])
        matches = _parse_matches(raw, rule="def $FUNC")
        assert len(matches) == 1
        assert matches[0] == AstGrepMatch(
            file="src/main.py",
            line=10,
            column=0,
            text="def hello():",
            rule="def $FUNC",
        )

    def test_empty_string_returns_empty(self) -> None:
        assert _parse_matches("") == []
        assert _parse_matches("   ") == []

    def test_invalid_json_returns_empty(self) -> None:
        assert _parse_matches("not json") == []

    def test_multiple_matches(self) -> None:
        raw = json.dumps([
            {
                "file": "a.py",
                "text": "x = 1",
                "range": {"start": {"line": 1, "column": 0}},
            },
            {
                "file": "b.py",
                "text": "y = 2",
                "range": {"start": {"line": 5, "column": 4}},
            },
        ])
        matches = _parse_matches(raw)
        assert len(matches) == 2
        assert matches[1].file == "b.py"
        assert matches[1].line == 5
        assert matches[1].column == 4

    def test_missing_fields_use_defaults(self) -> None:
        raw = json.dumps([{"ruleId": "no-eval"}])
        matches = _parse_matches(raw)
        assert len(matches) == 1
        assert matches[0].file == ""
        assert matches[0].line == 0
        assert matches[0].rule == "no-eval"


# ── Async tests with mocked subprocess ───────────────────────────


class TestIsAvailable:
    async def test_returns_true_when_sg_exists(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock()

        with patch("theswarm.tools.ast_grep.asyncio.create_subprocess_exec", return_value=mock_proc):
            assert await is_available() is True

    async def test_returns_false_when_sg_missing(self) -> None:
        with patch(
            "theswarm.tools.ast_grep.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError,
        ):
            assert await is_available() is False

    async def test_returns_false_when_nonzero_exit(self) -> None:
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.wait = AsyncMock()

        with patch("theswarm.tools.ast_grep.asyncio.create_subprocess_exec", return_value=mock_proc):
            assert await is_available() is False


class TestSearch:
    async def test_returns_matches_from_sg_output(self) -> None:
        sg_output = json.dumps([
            {
                "file": "foo.py",
                "text": "print(x)",
                "range": {"start": {"line": 3, "column": 0}},
            },
        ])
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(
            return_value=(sg_output.encode(), b""),
        )
        mock_proc.returncode = 0

        with patch("theswarm.tools.ast_grep.asyncio.create_subprocess_exec", return_value=mock_proc):
            results = await search("print($ARG)", "/tmp/repo")

        assert len(results) == 1
        assert results[0].file == "foo.py"
        assert results[0].rule == "print($ARG)"

    async def test_returns_empty_when_sg_not_found(self) -> None:
        with patch(
            "theswarm.tools.ast_grep.asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError,
        ):
            results = await search("$X", "/tmp/repo")
            assert results == []

    async def test_returns_empty_on_timeout(self) -> None:
        import asyncio

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_proc.kill = AsyncMock()

        with patch("theswarm.tools.ast_grep.asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("theswarm.tools.ast_grep.asyncio.wait_for", side_effect=asyncio.TimeoutError):
                results = await search("$X", "/tmp/repo", timeout=1)
                assert results == []


class TestCheckPatterns:
    async def test_aggregates_results(self) -> None:
        match_a = AstGrepMatch(file="a.py", line=1, column=0, text="x", rule="r1")
        match_b = AstGrepMatch(file="b.py", line=2, column=0, text="y", rule="r2")

        call_count = 0

        async def mock_search(pattern: str, path: str, **kwargs: object) -> list[AstGrepMatch]:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [match_a]
            return [match_b]

        rules = [
            {"pattern": "print($X)"},
            {"pattern": "eval($X)", "lang": "python"},
        ]

        with patch("theswarm.tools.ast_grep.search", side_effect=mock_search):
            results = await check_patterns("/tmp/repo", rules)

        assert len(results) == 2
        assert results[0] == match_a
        assert results[1] == match_b

    async def test_skips_empty_patterns(self) -> None:
        with patch("theswarm.tools.ast_grep.search", new_callable=AsyncMock) as mock_s:
            mock_s.return_value = []
            await check_patterns("/tmp", [{"pattern": ""}, {"pattern": "x"}])
            mock_s.assert_called_once()
