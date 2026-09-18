"""A demo launch whose process has already exited must not wait it out.

Cycle 5b1da00155c2: the Dev's ALREADY_SATISFIED answer left the target
uninstalled, so every one of QA's three demo launches (E2E, screenshots,
video) started `python -m theswarm serve`, watched it die immediately on
`No module named theswarm`, and then polled the dead process for the full
90s `ready_seconds` window anyway — 4.5 minutes spent waiting on nothing,
and the report showed a bare "0 screenshots" with no reason.

`wait_for_http_ready`'s `is_dead` hook (readiness.py) now raises
`ProcessExited` the moment `server_proc.returncode is not None`, and each
demo-launch node turns that into a `demo_launch_error` string — the server's
last output line — that shows up on the report card instead of a silent
zero.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from theswarm.agents.qa import capture_demo_screenshots, record_demo_video, run_e2e_tests


async def _dead_server_proc(last_output: bytes) -> AsyncMock:
    """A process that had already exited by the time readiness was checked."""
    proc = AsyncMock()
    proc.returncode = 1  # already exited
    proc.communicate = AsyncMock(return_value=(last_output, None))
    proc.wait = AsyncMock(return_value=1)
    proc.send_signal = MagicMock()
    proc.kill = MagicMock()
    return proc


async def test_screenshots_exit_immediately_on_a_dead_server(tmp_path):
    claude = MagicMock()
    dead_proc = await _dead_server_proc(
        b"Traceback (most recent call last):\nModuleNotFoundError: No module named theswarm\n",
    )
    recorder_cls = MagicMock()

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=dead_proc), \
         patch(
             "theswarm.infrastructure.recording.playwright_recorder.PlaywrightRecorder",
             recorder_cls,
         ):
        start = time.monotonic()
        state = {"workspace": str(tmp_path), "claude": claude}
        result = await capture_demo_screenshots(state)
        elapsed = time.monotonic() - start

    assert elapsed < 5.0  # not a 30s+ readiness wait
    assert result["demo_artifacts"] == []
    assert "server exited rc=1" in result["demo_launch_error"]
    assert "No module named theswarm" in result["demo_launch_error"]
    recorder_cls.assert_not_called()


async def test_e2e_exits_immediately_on_a_dead_server(tmp_path):
    e2e_dir = tmp_path / "tests" / "e2e"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "test_api_e2e.py").write_text("def test_x():\n    pass\n")

    claude = MagicMock()
    claude.run_tests = AsyncMock(return_value={"output": "1 passed", "passed": True})
    dead_proc = await _dead_server_proc(b"ModuleNotFoundError: No module named theswarm\n")

    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=dead_proc):
        start = time.monotonic()
        state = {"claude": claude, "workspace": str(tmp_path)}
        result = await run_e2e_tests(state)
        elapsed = time.monotonic() - start

    assert elapsed < 5.0
    assert result["e2e_passed"] is False
    assert "demo_launch_error" in result
    assert "No module named theswarm" in result["demo_launch_error"]
    # pytest must never have been invoked against a dead server.
    claude.run_tests.assert_not_called()


async def test_video_exits_immediately_on_a_dead_server(tmp_path):
    claude = MagicMock()
    dead_proc = await _dead_server_proc(b"No module named theswarm\n")

    with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=dead_proc):
        start = time.monotonic()
        state = {"workspace": str(tmp_path), "claude": claude}
        result = await record_demo_video(state)
        elapsed = time.monotonic() - start

    assert elapsed < 5.0
    assert result["video_artifacts"] == []
    assert "No module named theswarm" in result["demo_launch_error"]
