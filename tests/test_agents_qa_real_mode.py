"""Tests for QA agent real-mode paths (write_e2e_tests, run_e2e_tests, run_security_scan, _find_system_python)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theswarm.agents.qa import (
    _find_system_python,
    run_e2e_tests,
    run_security_scan,
    write_e2e_tests,
)


# ── Helpers ───────────────────────────────────────────────────────────────


@dataclass
class FakeClaudeResult:
    text: str
    total_tokens: int = 500
    cost_usd: float = 0.01


def _make_claude_mock(run_return: FakeClaudeResult | None = None) -> MagicMock:
    claude = MagicMock()
    if run_return is not None:
        claude.run = AsyncMock(return_value=run_return)
    claude.run_tests = AsyncMock(return_value={"output": "", "passed": True})
    return claude


# ── write_e2e_tests ──────────────────────────────────────────────────────


async def test_write_e2e_tests_writes_plain_python(tmp_path):
    """When claude.run returns Python code starting with 'import', it is written to disk."""
    code = "import pytest\n\ndef test_hello():\n    assert True\n"
    claude = _make_claude_mock(FakeClaudeResult(text=code))

    state = {"claude": claude, "workspace": str(tmp_path), "github": None}
    result = await write_e2e_tests(state)

    test_file = tmp_path / "tests" / "e2e" / "test_api_e2e.py"
    assert test_file.exists()
    content = test_file.read_text()
    assert content.startswith("import pytest")
    assert result["tokens_used"] == 500
    assert result["cost_usd"] == 0.01


async def test_write_e2e_tests_extracts_from_markdown_fences(tmp_path):
    """When claude.run returns code wrapped in markdown fences, extract and write it."""
    fenced = "```python\nimport os\n\ndef test_it():\n    pass\n```"
    claude = _make_claude_mock(FakeClaudeResult(text=fenced))

    state = {"claude": claude, "workspace": str(tmp_path), "github": None}
    result = await write_e2e_tests(state)

    test_file = tmp_path / "tests" / "e2e" / "test_api_e2e.py"
    assert test_file.exists()
    content = test_file.read_text()
    assert "import os" in content
    # Fences should be stripped
    assert "```" not in content
    assert result["tokens_used"] == 500


async def test_write_e2e_tests_skips_when_file_exists(tmp_path):
    """When the E2E test file already exists and is > 100 bytes, skip generation."""
    e2e_dir = tmp_path / "tests" / "e2e"
    e2e_dir.mkdir(parents=True)
    test_file = e2e_dir / "test_api_e2e.py"
    test_file.write_text("x" * 200)

    claude = _make_claude_mock(FakeClaudeResult(text="import pytest"))
    state = {"claude": claude, "workspace": str(tmp_path), "github": None}
    result = await write_e2e_tests(state)

    assert result["tokens_used"] == 0
    # claude.run should NOT have been called
    claude.run.assert_not_called()


async def test_write_e2e_tests_no_valid_python(tmp_path):
    """When claude returns text with no valid Python code, handle gracefully."""
    claude = _make_claude_mock(FakeClaudeResult(text="This is just plain text with no code at all."))

    state = {"claude": claude, "workspace": str(tmp_path), "github": None}
    result = await write_e2e_tests(state)

    # File should NOT be written
    test_file = tmp_path / "tests" / "e2e" / "test_api_e2e.py"
    assert not test_file.exists()
    # Tokens are still counted
    assert result["tokens_used"] == 500


async def test_write_e2e_tests_with_github_issues(tmp_path):
    """When github is provided, closed issues are included in the prompt."""
    code = "import pytest\n\ndef test_api():\n    pass\n"
    claude = _make_claude_mock(FakeClaudeResult(text=code))

    github = MagicMock()
    github.get_issues = AsyncMock(return_value=[
        {"number": 1, "title": "Add user endpoint"},
        {"number": 2, "title": "Add todo endpoint"},
    ])

    state = {"claude": claude, "workspace": str(tmp_path), "github": github}
    result = await write_e2e_tests(state)

    # Verify github.get_issues was called
    github.get_issues.assert_called_once_with(state="closed")
    # Verify the prompt included issue info by checking claude.run was called
    call_args = claude.run.call_args
    prompt = call_args[0][0]
    assert "#1: Add user endpoint" in prompt
    assert result["tokens_used"] == 500


# ── run_e2e_tests ────────────────────────────────────────────────────────


async def test_run_e2e_tests_no_test_file(tmp_path):
    """When no E2E test file exists, skip with appropriate result."""
    claude = _make_claude_mock()
    state = {"claude": claude, "workspace": str(tmp_path)}
    result = await run_e2e_tests(state)

    assert result["e2e_passed"] is False
    assert "No E2E test file" in result["e2e_output"]
    assert result["e2e_counts"]["total"] == 0
    assert result["tokens_used"] == 0


async def test_run_e2e_tests_runs_full_pipeline(tmp_path):
    """When E2E file exists, start server, run tests, stop server."""
    # Create the E2E test file
    e2e_dir = tmp_path / "tests" / "e2e"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "test_api_e2e.py").write_text("import pytest\ndef test_x(): pass\n")

    claude = MagicMock()
    claude.run_tests = AsyncMock(return_value={
        "output": "===== 3 passed in 1.00s =====",
        "passed": True,
    })

    # Mock asyncio.create_subprocess_exec for pip install and uvicorn server
    fake_proc = AsyncMock()
    fake_proc.wait = AsyncMock(return_value=0)
    fake_proc.send_signal = MagicMock()
    fake_proc.kill = MagicMock()

    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc), \
         patch("asyncio.sleep", new_callable=AsyncMock):
        state = {"claude": claude, "workspace": str(tmp_path)}
        result = await run_e2e_tests(state)

    assert result["e2e_passed"] is True
    assert result["e2e_counts"]["passed"] == 3
    assert result["e2e_counts"]["total"] == 3
    assert result["tokens_used"] == 0
    # Server process should have been signalled to stop
    fake_proc.send_signal.assert_called_once()


# ── run_security_scan ────────────────────────────────────────────────────


async def test_run_security_scan_clean(tmp_path):
    """When semgrep finds no HIGH findings, status is 'pass'."""
    import json

    semgrep_output = json.dumps({"results": [
        {"extra": {"severity": "WARNING"}, "check_id": "rule1"},
    ]})

    claude = MagicMock()
    claude.run_tests = AsyncMock(side_effect=[
        # semgrep call
        {"output": semgrep_output, "passed": True},
        # coverage call
        {"output": "5 passed", "passed": True},
    ])

    # Write a fake coverage.json
    cov_data = {"totals": {"percent_covered": 82.5}}
    cov_path = tmp_path / "coverage.json"
    cov_path.write_text(json.dumps(cov_data))

    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"):
        state = {"claude": claude, "workspace": str(tmp_path)}
        result = await run_security_scan(state)

    scan = result["security_scan"]
    assert scan["semgrep_status"] == "pass"
    assert scan["semgrep_high"] == 0
    assert scan["coverage_pct"] == 82.5
    assert scan["coverage_status"] == "pass"


async def test_run_security_scan_high_findings(tmp_path):
    """When semgrep finds HIGH severity findings, status is 'fail'."""
    import json

    semgrep_output = json.dumps({"results": [
        {"extra": {"severity": "HIGH"}, "check_id": "sql-injection"},
        {"extra": {"severity": "ERROR"}, "check_id": "xss"},
        {"extra": {"severity": "WARNING"}, "check_id": "info-leak"},
    ]})

    claude = MagicMock()
    claude.run_tests = AsyncMock(side_effect=[
        {"output": semgrep_output, "passed": True},
        {"output": "3 passed", "passed": True},
    ])

    cov_path = tmp_path / "coverage.json"
    cov_path.write_text(json.dumps({"totals": {"percent_covered": 75.0}}))

    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"):
        state = {"claude": claude, "workspace": str(tmp_path)}
        result = await run_security_scan(state)

    scan = result["security_scan"]
    assert scan["semgrep_status"] == "fail"
    assert scan["semgrep_high"] == 2  # HIGH + ERROR both count
    assert scan["coverage_pct"] == 75.0


async def test_run_security_scan_low_coverage(tmp_path):
    """When coverage is below 70%, coverage_status is 'fail'."""
    import json

    semgrep_output = json.dumps({"results": []})

    claude = MagicMock()
    claude.run_tests = AsyncMock(side_effect=[
        {"output": semgrep_output, "passed": True},
        {"output": "2 passed", "passed": True},
    ])

    cov_path = tmp_path / "coverage.json"
    cov_path.write_text(json.dumps({"totals": {"percent_covered": 55.0}}))

    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"):
        state = {"claude": claude, "workspace": str(tmp_path)}
        result = await run_security_scan(state)

    scan = result["security_scan"]
    assert scan["semgrep_status"] == "pass"
    assert scan["coverage_status"] == "fail"
    assert scan["coverage_pct"] == 55.0


async def test_run_security_scan_semgrep_exception(tmp_path):
    """When semgrep raises an exception, semgrep_status stays 'not_run'."""
    import json

    claude = MagicMock()
    claude.run_tests = AsyncMock(side_effect=[
        Exception("semgrep not found"),
        {"output": "1 passed", "passed": True},
    ])

    cov_path = tmp_path / "coverage.json"
    cov_path.write_text(json.dumps({"totals": {"percent_covered": 90.0}}))

    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"):
        state = {"claude": claude, "workspace": str(tmp_path)}
        result = await run_security_scan(state)

    scan = result["security_scan"]
    assert scan["semgrep_status"] == "not_run"
    assert scan["coverage_pct"] == 90.0


# ── _find_system_python ──────────────────────────────────────────────────


def test_find_system_python_finds_valid_binary(tmp_path):
    """When PATH contains a valid python3 binary outside the venv, return it."""
    # Create a fake python3 binary
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    python_bin = bin_dir / "python3"
    python_bin.write_text("#!/bin/sh\n")
    python_bin.chmod(0o755)

    with patch.dict(os.environ, {"PATH": str(bin_dir)}, clear=False), \
         patch("sys.prefix", "/some/venv"):
        result = _find_system_python()

    assert result == str(python_bin)


def test_find_system_python_skips_venv_python(tmp_path):
    """When PATH only has python3 inside the venv prefix, fall back to 'python3'."""
    venv_bin = tmp_path / "venv" / "bin"
    venv_bin.mkdir(parents=True)
    python_bin = venv_bin / "python3"
    python_bin.write_text("#!/bin/sh\n")
    python_bin.chmod(0o755)

    with patch.dict(os.environ, {"PATH": str(venv_bin)}, clear=False), \
         patch("sys.prefix", str(tmp_path / "venv")):
        result = _find_system_python()

    assert result == "python3"


def test_find_system_python_no_path():
    """When PATH is empty, return fallback 'python3'."""
    with patch.dict(os.environ, {"PATH": ""}, clear=False), \
         patch("sys.prefix", "/some/venv"):
        result = _find_system_python()

    assert result == "python3"
