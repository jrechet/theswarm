"""A commit that does not parse never leaves the workspace.

theswarm PR #74: the Dev agent was asked only to add a regression test. It
rewrote src/theswarm/agents/dev.py as +1 -381 and left
`SyntaxError: unterminated triple-quoted string literal` at line 75.
Thirteen test modules stopped collecting; both CI checks failed. Only the
CI gate stood between that and main — and when the agent edits its own
source, the file it truncates is the one doing the writing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from theswarm.tools.git import BrokenSyntax, _python_syntax_errors, commit_all


@pytest.fixture()
def repo(tmp_path):
    """A real git repo — the gate reads the index, so mocks would prove nothing."""
    for cmd in (["init", "-q"], ["config", "user.email", "t@t"],
                ["config", "user.name", "t"]):
        subprocess.run(["git", *cmd], cwd=tmp_path, check=True)
    (tmp_path / "ok.py").write_text("value = 1\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    return tmp_path


def _log(repo) -> str:
    return subprocess.run(["git", "log", "--oneline"], cwd=repo,
                          capture_output=True, text=True).stdout


# ── The gate itself ────────────────────────────────────────────────────


def test_the_truncation_from_pr_74_is_detected(tmp_path):
    (tmp_path / "dev.py").write_text('"""Docstring that never closes\n\nx = 1\n')
    [error] = _python_syntax_errors(str(tmp_path), ["dev.py"])
    assert "dev.py" in error


def test_sound_python_passes(tmp_path):
    (tmp_path / "a.py").write_text("def f() -> int:\n    return 1\n")
    assert _python_syntax_errors(str(tmp_path), ["a.py"]) == []


def test_non_python_files_are_not_parsed(tmp_path):
    (tmp_path / "x.md").write_text('"""not python at all')
    (tmp_path / "y.html").write_text("<p>{{ unclosed ")
    assert _python_syntax_errors(str(tmp_path), ["x.md", "y.html"]) == []


def test_a_deleted_file_is_not_a_syntax_error(tmp_path):
    """Staged deletions and renames leave paths with nothing behind them."""
    assert _python_syntax_errors(str(tmp_path), ["gone.py"]) == []


# ── Through commit_all, against a real repository ──────────────────────


async def test_a_broken_file_is_never_committed(repo):
    (repo / "ok.py").write_text('"""truncated\n')

    with pytest.raises(BrokenSyntax) as exc:
        await commit_all(str(repo), "feat: break everything")

    assert "ok.py" in str(exc.value)
    assert "base" in _log(repo) and _log(repo).count("\n") == 1


async def test_one_broken_file_blocks_the_whole_commit(repo):
    """Partial commits would leave the tree inconsistent with the task."""
    (repo / "good.py").write_text("value = 2\n")
    (repo / "bad.py").write_text("def f(:\n")

    with pytest.raises(BrokenSyntax):
        await commit_all(str(repo), "feat: mixed")

    assert "bad.py" in subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo,
        capture_output=True, text=True).stdout


async def test_sound_changes_still_commit(repo):
    (repo / "ok.py").write_text("value = 2\n")

    assert await commit_all(str(repo), "feat: fine") is True
    assert "feat: fine" in _log(repo)


async def test_nothing_to_commit_is_still_reported_as_such(repo):
    assert await commit_all(str(repo), "feat: noop") is False


async def test_the_error_names_the_files_so_the_log_is_actionable(repo):
    for name in ("a.py", "b.py"):
        (repo / name).write_text("def f(:\n")

    with pytest.raises(BrokenSyntax, match=r"a\.py.*b\.py"):
        await commit_all(str(repo), "feat: two broken")
