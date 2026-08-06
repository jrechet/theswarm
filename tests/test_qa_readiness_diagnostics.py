"""A target app that fails to boot must say why.

Prod repro (cycle 8170b32ca48f): the target's uvicorn died on import because
its requirements.txt omitted a module its conftest imported. Its stdout was
piped but never read, so the logs showed only a bare
``ERR_CONNECTION_REFUSED`` with no cause anywhere — the interesting error was
captured and thrown away.
"""

from __future__ import annotations

import asyncio
import logging

from theswarm.agents.qa import _log_readiness_failure
from theswarm.infrastructure.resilience import ReadinessTimeout


class _ExitedProc:
    """A server that crashed on import and left its traceback on stdout."""

    returncode = 1

    async def communicate(self):
        return (b"ModuleNotFoundError: No module named 'httpx'\n", b"")


class _RunningProc:
    """Alive but not serving — reading it would block forever."""

    returncode = None
    communicate_called = False

    async def communicate(self):
        type(self).communicate_called = True
        await asyncio.sleep(60)


class _SilentProc:
    returncode = 2

    async def communicate(self):
        return (b"", b"")


async def test_crashed_server_output_reaches_the_log(caplog):
    with caplog.at_level(logging.WARNING):
        await _log_readiness_failure(
            "QA screenshots", _ExitedProc(), ReadinessTimeout("not ready after 30s"),
        )

    message = caplog.text
    assert "No module named 'httpx'" in message
    assert "rc=1" in message


async def test_running_server_is_not_read(caplog):
    """communicate() on a live process would hang the phase."""
    with caplog.at_level(logging.WARNING):
        await _log_readiness_failure(
            "QA E2E", _RunningProc(), ReadinessTimeout("not ready after 30s"),
        )

    assert _RunningProc.communicate_called is False
    assert "still running but not serving" in caplog.text


async def test_silent_crash_is_reported_without_output(caplog):
    with caplog.at_level(logging.WARNING):
        await _log_readiness_failure(
            "QA video", _SilentProc(), ReadinessTimeout("not ready after 30s"),
        )

    assert "rc=2" in caplog.text
    assert "no output captured" in caplog.text


def test_every_readiness_handler_uses_the_diagnostic():
    """All three server starts must report, not swallow, a boot failure."""
    import inspect

    from theswarm.agents import qa

    source = inspect.getsource(qa)
    assert source.count("_log_readiness_failure(") == 4  # 1 def + 3 call sites
    assert "running tests anyway" not in source
    assert "capturing anyway" not in source
    assert "recording anyway" not in source
