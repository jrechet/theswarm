"""QA brings pytest-cov into the swarm's own venv when the target lacks it.

concert-tour-app does not list pytest-cov, so every QA report on 2026-09-25
read coverage `not_run` ("pytest-cov not installed") under a passing suite.
QA already installs pytest-playwright into the target's `.venv-swarm` for
its E2E run; that venv is the swarm's, not the target's code and not
TheSwarm's own. Any other interpreter is never touched.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from theswarm.agents.qa import run_unit_tests

SWARM_PYTHON = "/ws/concert-tour-app/.venv-swarm/bin/python"


async def _run(tmp_path, python, answers):
    claude = MagicMock()
    claude.run_tests = AsyncMock(side_effect=answers)
    with patch("theswarm.agents.qa._find_system_python", return_value=python):
        result = await run_unit_tests({"claude": claude, "workspace": str(tmp_path)})
    return claude, result


async def test_the_plugin_is_installed_into_the_swarm_venv_and_coverage_runs(tmp_path):
    (tmp_path / "coverage.json").write_text(json.dumps({"totals": {"percent_covered": 91.0}}))

    claude, result = await _run(tmp_path, SWARM_PYTHON, [
        {"output": "ModuleNotFoundError", "passed": False},  # import pytest_cov
        {"output": "", "passed": True},                      # pip install pytest-cov
        {"output": "9 passed in 1s", "passed": True},        # the suite
    ])

    install = claude.run_tests.call_args_list[1][0][1]
    assert install == [SWARM_PYTHON, "-m", "pip", "install", "-q", "pytest-cov"]
    suite = claude.run_tests.call_args_list[2][0][1]
    assert "--cov=src" in suite
    assert result["security_scan"]["coverage_pct"] == 91.0
    assert result["security_scan"]["coverage_status"] == "pass"


async def test_a_failed_install_leaves_coverage_not_run(tmp_path):
    claude, result = await _run(tmp_path, SWARM_PYTHON, [
        {"output": "ModuleNotFoundError", "passed": False},
        {"output": "ERROR: no network", "passed": False},
        {"output": "9 passed in 1s", "passed": True},
    ])

    assert "--cov=src" not in claude.run_tests.call_args_list[2][0][1]
    assert result["security_scan"]["coverage_status"] == "not_run"
    assert result["tests_passed"] is True


async def test_another_interpreter_is_never_installed_into(tmp_path):
    claude, result = await _run(tmp_path, "/usr/bin/python3", [
        {"output": "ModuleNotFoundError", "passed": False},
        {"output": "9 passed in 1s", "passed": True},
    ])

    commands = [call[0][1] for call in claude.run_tests.call_args_list]
    assert not any("pip" in command for command in commands)
    assert result["security_scan"]["coverage_reason"] == "pytest-cov not installed"
