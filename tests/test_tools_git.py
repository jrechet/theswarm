"""Tests for theswarm.tools.git — local git operations."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from theswarm.tools.git import (
    _run_git,
    cleanup_workspace,
    clone_repo,
    commit_all,
    create_branch,
    get_diff_stat,
    push_branch,
)


@pytest.fixture()
def mock_subprocess(mocker):
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"output", b""))
    mocker.patch("asyncio.create_subprocess_exec", return_value=mock_proc)
    return mock_proc


# ── _run_git ───────────────────────────────────────────────────────────


async def test_run_git_success(mock_subprocess):
    result = await _run_git("status")
    assert result == "output"


async def test_run_git_failure_with_check(mock_subprocess):
    mock_subprocess.returncode = 1
    mock_subprocess.communicate = AsyncMock(return_value=(b"", b"error details"))
    with pytest.raises(RuntimeError, match="git status failed"):
        await _run_git("status", check=True)


async def test_run_git_failure_without_check(mock_subprocess):
    mock_subprocess.returncode = 1
    mock_subprocess.communicate = AsyncMock(return_value=(b"some output", b"warn"))
    result = await _run_git("status", check=False)
    assert result == "some output"


# ── clone_repo ─────────────────────────────────────────────────────────


async def test_clone_repo_existing(mock_subprocess, mocker):
    mocker.patch("os.path.isdir", return_value=True)
    result = await clone_repo("https://github.com/o/r.git", "/tmp/repo")
    assert result == "/tmp/repo"
    # Should not have called git clone — only checkout + pull
    import asyncio
    calls = asyncio.create_subprocess_exec.call_args_list
    git_cmds = [c.args[1] for c in calls]
    assert "clone" not in git_cmds
    assert "checkout" in git_cmds
    assert "pull" in git_cmds


async def test_clone_repo_fresh(mock_subprocess, mocker):
    mocker.patch("os.path.isdir", return_value=False)
    mocker.patch("os.makedirs")
    result = await clone_repo("https://github.com/o/r.git", "/tmp/repo")
    assert result == "/tmp/repo"
    import asyncio
    calls = asyncio.create_subprocess_exec.call_args_list
    git_cmds = [c.args[1] for c in calls]
    assert "clone" in git_cmds


# ── create_branch ──────────────────────────────────────────────────────


async def test_create_branch(mock_subprocess):
    await create_branch("/tmp/repo", "feat/new", base="main")
    import asyncio
    calls = asyncio.create_subprocess_exec.call_args_list
    # Expect: checkout main, pull, checkout -b feat/new
    assert len(calls) == 3
    assert calls[0].args[1] == "checkout"
    assert calls[0].args[2] == "main"
    assert calls[2].args[1] == "checkout"
    assert calls[2].args[2] == "-b"
    assert calls[2].args[3] == "feat/new"


# ── commit_all ─────────────────────────────────────────────────────────


async def test_commit_all_with_changes(mocker):
    """When status returns non-empty, add + commit should be called."""
    call_count = 0

    async def fake_subprocess(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        proc = AsyncMock()
        proc.returncode = 0
        # The second git call is `status --porcelain`; return non-empty
        if args[1] == "status":
            proc.communicate = AsyncMock(return_value=(b"M file.py", b""))
        else:
            proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    mocker.patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess)
    result = await commit_all("/tmp/repo", "test commit")
    assert result is True
    # 3 calls: add -A, status --porcelain, commit -m
    import asyncio
    assert asyncio.create_subprocess_exec.call_count == 3


async def test_commit_all_no_changes(mocker):
    """When status returns empty, no commit should happen."""

    async def fake_subprocess(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 0
        if args[1] == "status":
            proc.communicate = AsyncMock(return_value=(b"", b""))
        else:
            proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    mocker.patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess)
    result = await commit_all("/tmp/repo", "test commit")
    assert result is False
    # Only 2 calls: add -A, status --porcelain (no commit)
    import asyncio
    assert asyncio.create_subprocess_exec.call_count == 2


# ── push_branch ────────────────────────────────────────────────────────


async def test_push_branch(mock_subprocess):
    await push_branch("/tmp/repo", "feat/new")
    import asyncio
    call = asyncio.create_subprocess_exec.call_args
    assert call.args == ("git", "push", "-u", "origin", "feat/new")


# ── get_diff_stat ──────────────────────────────────────────────────────


async def test_get_diff_stat(mock_subprocess):
    mock_subprocess.communicate = AsyncMock(
        return_value=(b" file.py | 2 +-\n 1 file changed", b"")
    )
    result = await get_diff_stat("/tmp/repo")
    assert "file.py" in result


# ── cleanup_workspace ──────────────────────────────────────────────────


async def test_cleanup_workspace_existing(mocker):
    mocker.patch("os.path.isdir", return_value=True)
    mock_rmtree = mocker.patch("shutil.rmtree")
    await cleanup_workspace("/tmp/repo")
    mock_rmtree.assert_called_once_with("/tmp/repo")


async def test_cleanup_workspace_nonexisting(mocker):
    mocker.patch("os.path.isdir", return_value=False)
    mock_rmtree = mocker.patch("shutil.rmtree")
    await cleanup_workspace("/tmp/repo")
    mock_rmtree.assert_not_called()
