"""Dev installs and tests with one interpreter, and allows a cold install.

Prod diagnosis (cycle 882694d44248): in the deploy container a bare ``pip``
resolves to ``/usr/local/bin/pip`` (system python) while a bare ``python``
resolves to ``/app/.venv/bin/python`` (TheSwarm's venv). Dependencies landed
in the system user site-packages, which the venv ignores, so the target's
tests never saw them. The install also measured 145s cold — over the old
120s cap, so it timed out on every run.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from theswarm.agents.dev import DEP_INSTALL_TIMEOUT_SECONDS, run_quality_gates


class _RecordingClaude:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], int]] = []

    async def run_tests(self, workdir, command, *, timeout=300):
        self.calls.append((list(command), timeout))
        return {"passed": True, "output": "", "exit_code": 0}


def _workspace_with_requirements(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    return str(tmp_path)


async def test_install_and_test_share_one_interpreter(tmp_path):
    claude = _RecordingClaude()
    state = {
        "task": {"number": 1},
        "workspace": _workspace_with_requirements(tmp_path),
        "claude": claude,
    }

    await run_quality_gates(state)

    install_cmd, _ = claude.calls[0]
    test_cmd, _ = claude.calls[1]
    assert install_cmd[1:4] == ["-m", "pip", "install"]
    assert test_cmd[1:3] == ["-m", "pytest"]
    # Same interpreter for both — this is the whole point
    assert install_cmd[0] == test_cmd[0]


async def test_no_bare_pip_or_python(tmp_path):
    """Bare names resolve to different interpreters in the deploy container."""
    claude = _RecordingClaude()
    state = {
        "task": {"number": 1},
        "workspace": _workspace_with_requirements(tmp_path),
        "claude": claude,
    }

    await run_quality_gates(state)

    for command, _ in claude.calls:
        assert command[0] not in ("pip", "python")


async def test_cold_install_gets_enough_time(tmp_path):
    claude = _RecordingClaude()
    state = {
        "task": {"number": 1},
        "workspace": _workspace_with_requirements(tmp_path),
        "claude": claude,
    }

    await run_quality_gates(state)

    _, install_timeout = claude.calls[0]
    assert install_timeout == DEP_INSTALL_TIMEOUT_SECONDS
    # A measured 145s cold install must fit comfortably
    assert install_timeout > 145


def test_dev_and_qa_resolve_the_same_interpreter():
    from theswarm.agents.base import find_system_python
    from theswarm.agents.qa import _find_system_python

    assert _find_system_python() == find_system_python()


def test_find_system_python_skips_the_active_venv():
    import sys

    from theswarm.agents.base import find_system_python

    resolved = find_system_python()
    # Must not hand back the venv the app itself runs in
    assert not resolved.startswith(sys.prefix + "/")
