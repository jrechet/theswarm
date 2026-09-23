"""A Claude child's `python` is the target's, never TheSwarm's own venv.

Cycle 83b584194589 (2026-09-23): the Dev's Bash could not find pytest, and
with TheSwarm's venv first on the container's PATH it ran `uv pip install -r
requirements.txt --python /app/.venv/bin/python`, replacing TheSwarm's
fastapi, pydantic and uvicorn with the target's pins under the running
server.
"""

from __future__ import annotations

import inspect
import os

import pytest

from theswarm.tools import claude as claude_mod
from theswarm.tools.claude import (
    TARGET_VENV_DIR,
    _child_env,
    _sdk_child_env,
    decide_tool_use,
)

OWN = "/app/.venv"


@pytest.fixture()
def in_theswarm_venv(monkeypatch):
    """Run as the container does: TheSwarm's venv first on PATH."""
    monkeypatch.setattr(claude_mod, "_own_venv", lambda: OWN)
    monkeypatch.setenv("PATH", os.pathsep.join([f"{OWN}/bin", "/usr/local/bin", "/usr/bin"]))
    monkeypatch.setenv("VIRTUAL_ENV", OWN)


@pytest.fixture()
def workspace(tmp_path):
    (tmp_path / TARGET_VENV_DIR / "bin").mkdir(parents=True)
    return str(tmp_path)


def test_the_marker_matches_the_agents_venv_dir():
    from theswarm.agents.base import TARGET_VENV_DIR as agents_dir

    assert TARGET_VENV_DIR == agents_dir


def test_theswarm_venv_leaves_the_path(in_theswarm_venv):
    env = _child_env()

    assert f"{OWN}/bin" not in env["PATH"].split(os.pathsep)
    assert "/usr/local/bin" in env["PATH"].split(os.pathsep)
    assert env["VIRTUAL_ENV"] == ""


def test_the_workspace_venv_comes_first(in_theswarm_venv, workspace):
    env = _child_env(workdir=workspace)

    first = env["PATH"].split(os.pathsep)[0]
    assert first == os.path.join(workspace, TARGET_VENV_DIR, "bin")
    assert env["VIRTUAL_ENV"] == os.path.join(workspace, TARGET_VENV_DIR)
    assert f"{OWN}/bin" not in env["PATH"].split(os.pathsep)


def test_the_sdk_child_overrides_rather_than_omits(in_theswarm_venv, workspace):
    """ClaudeAgentOptions.env is merged over os.environ: an omitted
    VIRTUAL_ENV would come back as TheSwarm's."""
    env = _sdk_child_env(workdir=workspace)

    assert env["VIRTUAL_ENV"] == os.path.join(workspace, TARGET_VENV_DIR)
    assert env["PATH"].split(os.pathsep)[0].endswith(f"{TARGET_VENV_DIR}/bin")


def test_the_sdk_options_carry_the_workspace(in_theswarm_venv, workspace):
    cli = claude_mod.ClaudeCLI(model="haiku")
    opts = cli._sdk_options("edit", workspace, "claude-haiku-4-5",
                            drop_oauth_env=False, resume=None)

    assert opts.env["VIRTUAL_ENV"] == os.path.join(workspace, TARGET_VENV_DIR)


def test_the_cli_child_carries_the_workspace():
    source = inspect.getsource(claude_mod.ClaudeCLI._run_cli)
    assert "_child_env(drop_oauth_env=drop_oauth_env, workdir=workdir)" in source


@pytest.mark.parametrize("command", [
    "uv pip install -q -r requirements.txt --python /app/.venv/bin/python",
    "/app/.venv/bin/python -m pip install -r requirements.txt",
    "/app/.venv/bin/pytest tests/",
])
def test_a_command_naming_theswarms_venv_is_refused(in_theswarm_venv, command):
    allowed, why = decide_tool_use("edit", "/ws", "Bash", {"command": command})

    assert not allowed
    assert TARGET_VENV_DIR in why


def test_the_targets_own_python_is_allowed(in_theswarm_venv):
    allowed, _ = decide_tool_use("edit", "/ws", "Bash",
                                 {"command": "python -m pytest tests/ -q"})
    assert allowed


def test_the_dev_builds_the_target_venv_before_claude_runs():
    from theswarm.agents import dev

    for fn in (dev.implement_task, dev.retry_implement):
        source = inspect.getsource(fn)
        assert "await ensure_target_venv(workspace)" in source, fn.__name__
        assert source.index("await ensure_target_venv(workspace)") < source.index("await claude.run("), fn.__name__
