"""Two harness runs on one day both publish their line of history.

Run 35908375032 was dispatched while 35907412563 was still running; the
workflow's concurrency group queued it, and its checkout was main as it
was at dispatch — without the line the first run pushed a few seconds
later. Both runs appended to the end of docs/harness-runs.jsonl, and the
publish step's `git rebase origin/main` stopped on a conflict. The file is
merged with `union` (.gitattributes), so the rebase keeps both lines.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HISTORY = "docs/harness-runs.jsonl"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, env=env, check=True, capture_output=True, text=True,
    ).stdout


def test_the_history_file_is_merged_with_union():
    out = _git(ROOT, "check-attr", "merge", "--", HISTORY)
    assert out.strip() == f"{HISTORY}: merge: union"


def test_two_runs_that_append_from_the_same_main_rebase_without_a_conflict(tmp_path):
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    shutil.copy(ROOT / ".gitattributes", repo / ".gitattributes")
    history = repo / HISTORY
    history.write_text('{"run": "earlier"}\n')
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")

    # The queued run: checked out at dispatch, appends its own line.
    _git(repo, "checkout", "-q", "-b", "queued")
    with history.open("a") as f:
        f.write('{"run": "35908375032"}\n')
    _git(repo, "commit", "-qam", "chore: harness run (queued)")

    # Meanwhile the run ahead of it published to main.
    _git(repo, "checkout", "-q", "main")
    with history.open("a") as f:
        f.write('{"run": "35907412563"}\n')
    _git(repo, "commit", "-qam", "chore: harness run (first)")

    _git(repo, "checkout", "-q", "queued")
    _git(repo, "rebase", "main")

    assert history.read_text().splitlines() == [
        '{"run": "earlier"}',
        '{"run": "35907412563"}',
        '{"run": "35908375032"}',
    ]
