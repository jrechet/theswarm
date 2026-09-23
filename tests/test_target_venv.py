"""V2 runtime, M5: the target runs in its own venv, inside its workspace.

Neither TheSwarm's venv nor the container's system python receives the
target's dependencies any more; the interpreter that installs is the one
that tests (the rule from prod cycle 882694d44248 still holds).
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from theswarm.agents import base
from theswarm.agents.base import TARGET_VENV_DIR, ensure_target_venv, find_system_python


def _fake_spawn(created: list[list[str]], *, rc: int = 0, make_python: bool = True):
    async def spawn(*argv, **_kwargs):
        created.append(list(argv))
        venv_dir = argv[-1]
        if make_python:
            os.makedirs(os.path.join(venv_dir, "bin"), exist_ok=True)
            with open(os.path.join(venv_dir, "bin", "python"), "w") as handle:
                handle.write("#!/bin/sh\n")
        proc = AsyncMock()
        proc.returncode = rc
        proc.communicate = AsyncMock(return_value=(b"", None))
        return proc
    return spawn


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("SWARM_TARGET_VENV", "1")
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "t"\nrequires-python = ">=3.10"\n')
    return str(tmp_path)


async def test_the_venv_is_built_with_uv_when_available(workspace, monkeypatch):
    spawned: list[list[str]] = []
    monkeypatch.setattr(base.shutil, "which", lambda name: "/usr/local/bin/uv" if name == "uv" else None)
    monkeypatch.setattr(base, "_system_python", lambda ws="": "/usr/bin/python3.12")
    with patch("theswarm.agents.base.asyncio.create_subprocess_exec", _fake_spawn(spawned)):
        python = await ensure_target_venv(workspace)

    assert python == os.path.join(workspace, TARGET_VENV_DIR, "bin", "python")
    (argv,) = spawned
    assert argv[:3] == ["/usr/local/bin/uv", "venv", "--seed"]
    assert "--python" in argv and argv[argv.index("--python") + 1] == "/usr/bin/python3.12"
    assert argv[-1] == os.path.join(workspace, TARGET_VENV_DIR)


async def test_without_uv_python_m_venv_is_used(workspace, monkeypatch):
    spawned: list[list[str]] = []
    monkeypatch.setattr(base.shutil, "which", lambda name: None)
    monkeypatch.setattr(base, "_system_python", lambda ws="": "/usr/bin/python3.12")
    with patch("theswarm.agents.base.asyncio.create_subprocess_exec", _fake_spawn(spawned)):
        await ensure_target_venv(workspace)
    (argv,) = spawned
    assert argv[:3] == ["/usr/bin/python3.12", "-m", "venv"]


async def test_an_existing_venv_is_reused_without_spawning(workspace):
    os.makedirs(os.path.join(workspace, TARGET_VENV_DIR, "bin"))
    open(os.path.join(workspace, TARGET_VENV_DIR, "bin", "python"), "w").close()
    with patch("theswarm.agents.base.asyncio.create_subprocess_exec", new=AsyncMock()) as spawn:
        python = await ensure_target_venv(workspace)
    assert python.endswith(f"{TARGET_VENV_DIR}/bin/python")
    assert spawn.await_count == 0


async def test_the_venv_python_is_the_one_dev_and_qa_then_choose(workspace):
    os.makedirs(os.path.join(workspace, TARGET_VENV_DIR, "bin"))
    open(os.path.join(workspace, TARGET_VENV_DIR, "bin", "python"), "w").close()
    assert find_system_python(workspace) == os.path.join(workspace, TARGET_VENV_DIR, "bin", "python")


async def test_a_failed_creation_falls_back_to_the_system_interpreter(workspace, monkeypatch):
    monkeypatch.setattr(base.shutil, "which", lambda name: None)
    monkeypatch.setattr(base, "_system_python", lambda ws="": "/usr/bin/python3.12")
    with patch("theswarm.agents.base.asyncio.create_subprocess_exec", _fake_spawn([], rc=1, make_python=False)):
        assert await ensure_target_venv(workspace) == ""
    assert find_system_python(workspace) == "/usr/bin/python3.12"


@pytest.mark.parametrize("reason", ["disabled", "no-workspace", "no-manifest"])
async def test_nothing_is_built_when_there_is_nothing_to_build(tmp_path, monkeypatch, reason):
    monkeypatch.setenv("SWARM_TARGET_VENV", "0" if reason == "disabled" else "1")
    workspace = "/nowhere/at/all" if reason == "no-workspace" else str(tmp_path)
    if reason == "disabled":
        (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\n")
    with patch("theswarm.agents.base.asyncio.create_subprocess_exec", new=AsyncMock()) as spawn:
        assert await ensure_target_venv(workspace) == ""
    assert spawn.await_count == 0


def test_the_suite_never_builds_a_venv_by_default():
    assert os.environ.get("SWARM_TARGET_VENV") == "0"
