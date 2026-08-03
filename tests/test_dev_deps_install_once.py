"""Dependencies install once per dev iteration, not once per retry.

Prod repro (cycle 1d816463e34b): ``pip install -r requirements.txt`` hangs
for its full 120s timeout in the deploy container and always fails. The
Ralph Loop re-enters ``run_quality_gates`` after every retry, so three
identical installs ate 360s of the 480s phase budget and the phase timeout
killed the iteration before ``open_pull_request`` could run — no PR, even
though the commit had landed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from theswarm.agents.dev import run_quality_gates


class _FakeClaude:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    async def run_tests(self, workdir, command, *, timeout=300):
        self.commands.append(list(command))
        return {"passed": False, "output": "boom", "exit_code": 1}


def _write_requirements(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    return str(tmp_path)


def _install_calls(claude: _FakeClaude) -> list[list[str]]:
    return [c for c in claude.commands if "pip" in c]


async def test_first_run_installs_dependencies(tmp_path):
    claude = _FakeClaude()
    state = {"task": {"number": 1}, "workspace": _write_requirements(tmp_path), "claude": claude}

    result = await run_quality_gates(state)

    assert len(_install_calls(claude)) == 1
    assert result["deps_installed"] is True


async def test_retry_run_skips_reinstall(tmp_path):
    """The expensive, always-failing install must not repeat on a retry."""
    claude = _FakeClaude()
    state = {
        "task": {"number": 1},
        "workspace": _write_requirements(tmp_path),
        "claude": claude,
        "deps_installed": True,
    }

    result = await run_quality_gates(state)

    assert _install_calls(claude) == []
    assert result["deps_installed"] is True
    # pytest still runs — only the install is skipped
    assert any("pytest" in c for c in claude.commands)


async def test_no_requirements_file_skips_install(tmp_path):
    claude = _FakeClaude()
    state = {"task": {"number": 1}, "workspace": str(tmp_path), "claude": claude}

    await run_quality_gates(state)

    assert _install_calls(claude) == []


async def test_deps_installed_is_declared_in_state():
    from theswarm.config import AgentState

    assert "deps_installed" in AgentState.__annotations__
