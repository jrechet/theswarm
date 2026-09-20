"""The interpreter must satisfy what the target declares.

`find_system_python` took the first non-venv `python3` on PATH. On a host
where an older one comes first — 3.11.6 ahead of 3.12.0 — a target
declaring `requires-python = ">=3.12"` could never install:

    ERROR: Package 'theswarm' requires a different Python: 3.11.6 not in '>=3.12'

Local cycle targeted-160-20260919T133731Z died of exactly that, and every
gate downstream reported a fiction about it. The deploy container never
hits it (its system python is new enough), which is why it took running a
cycle on a laptop to surface.

Dev and QA share this function and must keep agreeing on the interpreter,
so the choice is made the same way for both.
"""

from __future__ import annotations

import os

from theswarm.agents.base import find_system_python


def _fake_python(directory, version: str) -> str:
    """An executable that answers like an interpreter of that version."""
    directory.mkdir(parents=True, exist_ok=True)
    exe = directory / "python3"
    exe.write_text(f"#!/bin/sh\necho {version}\n")
    exe.chmod(0o755)
    return str(exe)


def _pyproject(workspace, requires: str | None) -> str:
    workspace.mkdir(parents=True, exist_ok=True)
    body = '[project]\nname = "target"\nversion = "0.1.0"\n'
    if requires is not None:
        body += f'requires-python = "{requires}"\n'
    (workspace / "pyproject.toml").write_text(body)
    return str(workspace)


def test_skips_an_interpreter_the_target_refuses(tmp_path, monkeypatch):
    old = _fake_python(tmp_path / "old", "3.11.6")
    new = _fake_python(tmp_path / "new", "3.12.0")
    workspace = _pyproject(tmp_path / "ws", ">=3.12")

    monkeypatch.setenv(
        "PATH", os.pathsep.join([str(tmp_path / "old"), str(tmp_path / "new")]),
    )

    chosen = find_system_python(workspace)

    assert chosen == new, (
        f"{old} cannot install a >=3.12 target; picking it makes the install "
        "fail and every downstream gate report a fiction"
    )


def test_without_a_declaration_the_first_on_path_still_wins(tmp_path, monkeypatch):
    old = _fake_python(tmp_path / "old", "3.11.6")
    _fake_python(tmp_path / "new", "3.12.0")
    workspace = _pyproject(tmp_path / "ws", None)

    monkeypatch.setenv(
        "PATH", os.pathsep.join([str(tmp_path / "old"), str(tmp_path / "new")]),
    )

    assert find_system_python(workspace) == old


def test_no_workspace_keeps_the_original_behaviour(tmp_path, monkeypatch):
    old = _fake_python(tmp_path / "old", "3.11.6")
    _fake_python(tmp_path / "new", "3.12.0")

    monkeypatch.setenv(
        "PATH", os.pathsep.join([str(tmp_path / "old"), str(tmp_path / "new")]),
    )

    assert find_system_python() == old


def test_falls_back_rather_than_returning_nothing(tmp_path, monkeypatch):
    """No candidate satisfies the spec: pick one and let the install speak."""
    old = _fake_python(tmp_path / "old", "3.11.6")
    workspace = _pyproject(tmp_path / "ws", ">=3.14")

    monkeypatch.setenv("PATH", str(tmp_path / "old"))

    assert find_system_python(workspace) == old
