"""#135: QA must run the target's suite once, not twice.

`run_unit_tests` used to produce the verdict, then `run_security_scan` ran
the whole suite again with `--cov` just for the coverage figure — on
TheSwarm's own ~4-minute suite that could burn the `qa` phase budget before
the demo even started. Now `run_unit_tests` adds the coverage flags to its
one pytest invocation when `pytest-cov` is importable in the target's
toolchain, and `run_security_scan` only runs semgrep.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from theswarm.agents.qa import run_unit_tests


async def test_cov_flags_added_when_pytest_cov_importable(tmp_path):
    claude = MagicMock()
    claude.run_tests = AsyncMock(side_effect=[
        {"output": "", "passed": True},          # import pytest_cov check
        {"output": "5 passed in 1s", "passed": True},  # the pytest run itself
    ])
    (tmp_path / "coverage.json").write_text(
        json.dumps({"totals": {"percent_covered": 85.0}}),
    )

    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"):
        state = {"claude": claude, "workspace": str(tmp_path)}
        result = await run_unit_tests(state)

    _, pytest_command = claude.run_tests.call_args_list[1][0]
    assert "--cov=src" in pytest_command
    assert "--cov-report=json" in pytest_command
    assert result["security_scan"]["coverage_pct"] == 85.0
    assert result["security_scan"]["coverage_status"] == "pass"
    assert result["security_scan"]["coverage_reason"] == ""


async def test_cov_flags_omitted_when_pytest_cov_missing(tmp_path):
    claude = MagicMock()
    claude.run_tests = AsyncMock(side_effect=[
        {"output": "ModuleNotFoundError", "passed": False},  # import check fails
        {"output": "5 passed in 1s", "passed": True},
    ])

    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"):
        state = {"claude": claude, "workspace": str(tmp_path)}
        result = await run_unit_tests(state)

    _, pytest_command = claude.run_tests.call_args_list[1][0]
    assert "--cov=src" not in pytest_command
    assert "--cov-report=json" not in pytest_command
    scan = result["security_scan"]
    assert scan["coverage_status"] == "not_run"
    assert scan["coverage_reason"] == "pytest-cov not installed"
    assert scan["coverage_pct"] == 0.0
    # The verdict itself is unaffected by the missing plugin.
    assert result["tests_passed"] is True
    assert result["test_counts"]["passed"] == 5


async def test_low_coverage_fails_the_gate(tmp_path):
    claude = MagicMock()
    claude.run_tests = AsyncMock(side_effect=[
        {"output": "", "passed": True},
        {"output": "5 passed in 1s", "passed": True},
    ])
    (tmp_path / "coverage.json").write_text(
        json.dumps({"totals": {"percent_covered": 55.0}}),
    )

    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"):
        state = {"claude": claude, "workspace": str(tmp_path)}
        result = await run_unit_tests(state)

    scan = result["security_scan"]
    assert scan["coverage_pct"] == 55.0
    assert scan["coverage_status"] == "fail"


async def test_missing_coverage_json_is_not_run(tmp_path):
    """pytest-cov importable but no coverage.json produced (e.g. -k filtered everything out)."""
    claude = MagicMock()
    claude.run_tests = AsyncMock(side_effect=[
        {"output": "", "passed": True},
        {"output": "0 passed in 1s", "passed": True},
    ])

    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"):
        state = {"claude": claude, "workspace": str(tmp_path)}
        result = await run_unit_tests(state)

    scan = result["security_scan"]
    assert scan["coverage_status"] == "not_run"
    assert scan["coverage_reason"] == "coverage.json not found"


async def test_timeout_marks_coverage_not_run_too(tmp_path):
    claude = MagicMock()
    claude.run_tests = AsyncMock(side_effect=[
        {"output": "", "passed": True},
        {"output": "Timed out after 900s", "passed": False, "exit_code": -1},
        {"output": "10 tests collected in 0.5s", "passed": False, "exit_code": 0},
    ])

    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"):
        state = {"claude": claude, "workspace": str(tmp_path)}
        result = await run_unit_tests(state)

    scan = result["security_scan"]
    assert scan["coverage_status"] == "not_run"
    assert scan["coverage_reason"] == "did not finish within 900s (10 tests collected)"
    assert result["unit_tests_not_run_reason"] == "did not finish within 900s (10 tests collected)"
