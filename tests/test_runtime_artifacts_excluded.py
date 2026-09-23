"""Runtime artifacts never reach a commit (V2 M5, and the old `git add -A` gap).

`commit_all` adds everything and `create_branch` cleans everything; both
honour .git/info/exclude, which stays local to the clone. The target's
own .gitignore is not ours to edit.
"""

from __future__ import annotations

import os

from theswarm.tools.git import RUNTIME_EXCLUDES, exclude_locally


def _clone(tmp_path):
    os.makedirs(tmp_path / ".git" / "info")
    return str(tmp_path)


def test_the_venv_the_worktrees_and_test_debris_are_excluded(tmp_path):
    workdir = _clone(tmp_path)
    assert exclude_locally(workdir) is True
    lines = (tmp_path / ".git" / "info" / "exclude").read_text().splitlines()
    for pattern in (".venv-swarm/", ".worktrees/", "test.db", "test.db-*", ".coverage", "coverage.json"):
        assert pattern in lines
    assert set(RUNTIME_EXCLUDES) <= set(lines)


def test_exclusion_is_idempotent_and_keeps_what_was_there(tmp_path):
    workdir = _clone(tmp_path)
    (tmp_path / ".git" / "info" / "exclude").write_text("# theirs\nlocal-notes.md\n")
    exclude_locally(workdir)
    exclude_locally(workdir)
    text = (tmp_path / ".git" / "info" / "exclude").read_text()
    assert text.startswith("# theirs\nlocal-notes.md\n")
    assert text.count(".venv-swarm/") == 1


def test_a_directory_that_is_not_a_clone_is_left_alone(tmp_path):
    assert exclude_locally(str(tmp_path)) is False
    assert not (tmp_path / ".git").exists()
