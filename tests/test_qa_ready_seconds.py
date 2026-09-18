"""QA's budgets on the swarm's own repo.

Prod cycle 5f8f0f63f58c reached QA on TheSwarm's own repository and produced
a blank demo: the unit-test run hit a 120s cap and was read as "0 passed, 0
failed" (a vacuous pass), the readiness wait was too tight for `theswarm
serve`'s ~30s boot so every screenshot attempt was ERR_CONNECTION_REFUSED,
and the E2E run picked up the target's own 132-test Playwright suite instead
of the file QA wrote. Four distinct budgets, all fixed here:
`demo.ready_seconds`, `QA_TEST_TIMEOUT_SECONDS`, the not-ready short-circuit
in `capture_demo_screenshots`, and the E2E file scope in `run_e2e_tests`.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from theswarm.agents.qa import (
    _demo_ready_seconds,
    capture_demo_screenshots,
    run_e2e_tests,
    run_unit_tests,
)
from theswarm.infrastructure.resilience import ReadinessTimeout


# ── _demo_ready_seconds ──────────────────────────────────────────────────


def test_undeclared_target_keeps_the_original_30s_default(tmp_path):
    assert _demo_ready_seconds(str(tmp_path)) == 30.0


def test_declared_ready_seconds_is_read(tmp_path):
    (tmp_path / "theswarm.yaml").write_text(
        "demo:\n  command: 'x'\n  ready_seconds: 90\n",
    )
    assert _demo_ready_seconds(str(tmp_path)) == 90.0


def test_non_numeric_ready_seconds_falls_back_to_default(tmp_path):
    (tmp_path / "theswarm.yaml").write_text(
        "demo:\n  command: 'x'\n  ready_seconds: soon\n",
    )
    assert _demo_ready_seconds(str(tmp_path)) == 30.0


def test_theswarms_own_manifest_declares_90s():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert _demo_ready_seconds(root) == 90.0


# ── run_unit_tests: a run that hits its cap is "not_run", not 0/0 ───────


async def test_unit_tests_timeout_is_reported_as_not_run(tmp_path):
    claude = MagicMock()
    claude.run_tests = AsyncMock(side_effect=[
        {"passed": False, "output": "", "exit_code": 1},  # pytest_cov import check
        {"passed": False, "output": "Timed out after 900s", "exit_code": -1},  # the run itself
        {"passed": False, "output": "2868 tests collected in 3.21s", "exit_code": 0},  # --collect-only probe
    ])

    state = {"claude": claude, "workspace": str(tmp_path)}
    result = await run_unit_tests(state)

    assert result["unit_tests_not_run_reason"] == "did not finish within 900s (2868 tests collected)"
    assert result["test_counts"] == {"passed": 0, "failed": 0, "errors": 0, "total": 0}
    assert result["tests_passed"] is False


async def test_unit_tests_timeout_with_unknown_collect_count(tmp_path):
    """The `--collect-only` probe can itself time out — say so, not a bare guess."""
    claude = MagicMock()
    claude.run_tests = AsyncMock(side_effect=[
        {"passed": False, "output": "", "exit_code": 1},
        {"passed": False, "output": "Timed out after 900s", "exit_code": -1},
        {"passed": False, "output": "Timed out after 60s", "exit_code": -1},
    ])

    state = {"claude": claude, "workspace": str(tmp_path)}
    result = await run_unit_tests(state)

    assert result["unit_tests_not_run_reason"] == "did not finish within 900s (test count unknown)"


async def test_unit_tests_timeout_uses_its_own_budget(tmp_path):
    from theswarm.agents.qa import QA_TEST_TIMEOUT_SECONDS

    claude = MagicMock()
    claude.run_tests = AsyncMock(return_value={"passed": True, "output": "1 passed"})

    state = {"claude": claude, "workspace": str(tmp_path)}
    await run_unit_tests(state)

    _, kwargs = claude.run_tests.call_args
    assert kwargs["timeout"] == QA_TEST_TIMEOUT_SECONDS == 900


async def test_unit_tests_that_finish_carry_no_reason(tmp_path):
    claude = MagicMock()
    claude.run_tests = AsyncMock(return_value={
        "passed": True,
        "output": "5 passed in 1.23s",
    })

    state = {"claude": claude, "workspace": str(tmp_path)}
    result = await run_unit_tests(state)

    assert result["unit_tests_not_run_reason"] == ""
    assert result["test_counts"]["passed"] == 5


# ── capture_demo_screenshots: not ready means no page.goto attempts ─────


async def _fake_server_proc():
    proc = AsyncMock()
    proc.returncode = None  # still "running" when readiness gives up
    proc.wait = AsyncMock(return_value=0)
    proc.send_signal = MagicMock()
    proc.kill = MagicMock()
    return proc


async def test_screenshots_skipped_when_server_never_ready(tmp_path):
    claude = MagicMock()
    fake_proc = await _fake_server_proc()

    def never_ready(*args, **kwargs):
        raise ReadinessTimeout("server at http://127.0.0.1:8001/ not ready after 30.0s")

    recorder_cls = MagicMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc), \
         patch(
             "theswarm.infrastructure.resilience.wait_for_http_ready",
             new_callable=AsyncMock,
             side_effect=never_ready,
         ), \
         patch(
             "theswarm.infrastructure.recording.playwright_recorder.PlaywrightRecorder",
             recorder_cls,
         ):
        state = {"workspace": str(tmp_path), "claude": claude}
        result = await capture_demo_screenshots(state)

    assert result["demo_artifacts"] == []
    assert result["tokens_used"] == 0
    assert "not ready after 30.0s" in result["demo_launch_error"]
    # No recorder was ever built — so no page.goto was attempted either.
    recorder_cls.assert_not_called()
    # The dead-end server is still cleaned up.
    fake_proc.send_signal.assert_called_once()


async def test_screenshots_use_declared_ready_seconds(tmp_path):
    (tmp_path / "theswarm.yaml").write_text(
        "demo:\n  command: '{python} -m x'\n  ready_seconds: 77\n",
    )
    claude = MagicMock()
    fake_proc = await _fake_server_proc()
    captured = {}

    def capture_timeout(url, *, timeout, interval, is_dead=None):
        captured["timeout"] = timeout
        raise ReadinessTimeout("boom")

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc), \
         patch(
             "theswarm.infrastructure.resilience.wait_for_http_ready",
             new_callable=AsyncMock,
             side_effect=capture_timeout,
         ):
        state = {"workspace": str(tmp_path), "claude": claude}
        await capture_demo_screenshots(state)

    assert captured["timeout"] == 77.0


# ── run_e2e_tests: only the file QA wrote, never the target's own suite ─


async def test_e2e_runs_only_the_generated_file(tmp_path):
    e2e_dir = tmp_path / "tests" / "e2e"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "test_api_e2e.py").write_text("def test_x():\n    pass\n")
    # A target's own Playwright suite living alongside QA's generated file.
    (e2e_dir / "test_target_playwright_suite.py").write_text(
        "def test_y():\n    pass\n" * 50,
    )

    claude = MagicMock()
    claude.run_tests = AsyncMock(return_value={"output": "1 passed", "passed": True})
    fake_proc = await _fake_server_proc()

    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc), \
         patch(
             "theswarm.infrastructure.resilience.wait_for_http_ready",
             new_callable=AsyncMock,
             return_value=0.1,
         ):
        state = {"claude": claude, "workspace": str(tmp_path)}
        await run_e2e_tests(state)

    _, test_args = claude.run_tests.call_args[0]
    expected_file = str(e2e_dir / "test_api_e2e.py")
    assert expected_file in test_args
    assert not any("test_target_playwright_suite" in a for a in test_args)
    assert str(e2e_dir) not in test_args  # never the bare directory either


async def test_e2e_uses_declared_ready_seconds(tmp_path):
    e2e_dir = tmp_path / "tests" / "e2e"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "test_api_e2e.py").write_text("def test_x():\n    pass\n")
    (tmp_path / "theswarm.yaml").write_text(
        "demo:\n  command: '{python} -m x'\n  ready_seconds: 42\n",
    )

    claude = MagicMock()
    claude.run_tests = AsyncMock(return_value={"output": "1 passed", "passed": True})
    fake_proc = await _fake_server_proc()
    captured = {}

    def capture_timeout(url, *, timeout, interval, is_dead=None):
        captured["timeout"] = timeout
        return 0.1

    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=fake_proc), \
         patch(
             "theswarm.infrastructure.resilience.wait_for_http_ready",
             new_callable=AsyncMock,
             side_effect=capture_timeout,
         ):
        state = {"claude": claude, "workspace": str(tmp_path)}
        await run_e2e_tests(state)

    assert captured["timeout"] == 42.0
