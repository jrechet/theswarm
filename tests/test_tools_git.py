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


async def test_commit_all_sets_identity_fallback_on_rc128(mocker):
    """Prod cycle adf70608e595: commit failed rc=128 'Author identity unknown'.

    commit_all must set a repo-local identity and retry once instead of
    failing the whole Dev iteration.
    """
    commit_attempts = 0
    config_calls: list[tuple[str, ...]] = []

    async def fake_subprocess(*args, **kwargs):
        nonlocal commit_attempts
        proc = AsyncMock()
        proc.returncode = 0
        if args[1] == "status":
            proc.communicate = AsyncMock(return_value=(b"M file.py", b""))
        elif "commit" in args:
            commit_attempts += 1
            if commit_attempts == 1:
                proc.returncode = 128
                proc.communicate = AsyncMock(return_value=(
                    b"",
                    b"Author identity unknown\n\n*** Please tell me who you are.",
                ))
            else:
                proc.communicate = AsyncMock(return_value=(b"", b""))
        elif args[1] == "config":
            config_calls.append(args[1:])
            proc.communicate = AsyncMock(return_value=(b"", b""))
        else:
            proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    mocker.patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess)
    result = await commit_all("/tmp/repo", "test commit")

    assert result is True
    assert commit_attempts == 2
    configured = {c[1] for c in config_calls}
    assert configured == {"user.name", "user.email"}


async def test_commit_all_other_error_still_raises(mocker):
    """A commit failure unrelated to identity must still propagate."""
    async def fake_subprocess(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 0
        if args[1] == "status":
            proc.communicate = AsyncMock(return_value=(b"M file.py", b""))
        elif "commit" in args:
            proc.returncode = 1
            proc.communicate = AsyncMock(return_value=(b"", b"pre-commit hook failed"))
        else:
            proc.communicate = AsyncMock(return_value=(b"", b""))
        return proc

    mocker.patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess)
    with pytest.raises(RuntimeError, match="pre-commit hook failed"):
        await commit_all("/tmp/repo", "test commit")


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


async def test_commit_all_passes_explicit_identity(mocker):
    """Commit must carry -c user.name/user.email — containers have no git config."""
    commit_calls = []

    async def fake_subprocess(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 0
        if args[1] == "status":
            proc.communicate = AsyncMock(return_value=(b"M file.py", b""))
        else:
            proc.communicate = AsyncMock(return_value=(b"", b""))
        if "commit" in args:
            commit_calls.append(args)
        return proc

    mocker.patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess)
    await commit_all("/tmp/repo", "feat: x")

    assert len(commit_calls) == 1
    args = commit_calls[0]
    assert "user.name=TheSwarm Dev Agent" in args
    assert "user.email=swarm-dev@jrec.fr" in args
    # -c flags must come before the subcommand
    assert args.index("user.name=TheSwarm Dev Agent") < args.index("commit")


async def test_commit_all_identity_env_override(mocker, monkeypatch):
    monkeypatch.setenv("SWARM_GIT_USER_NAME", "custom-bot")
    monkeypatch.setenv("SWARM_GIT_USER_EMAIL", "bot@example.com")
    commit_calls = []

    async def fake_subprocess(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 0
        if args[1] == "status":
            proc.communicate = AsyncMock(return_value=(b"M file.py", b""))
        else:
            proc.communicate = AsyncMock(return_value=(b"", b""))
        if "commit" in args:
            commit_calls.append(args)
        return proc

    mocker.patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess)
    await commit_all("/tmp/repo", "feat: x")

    assert "user.name=custom-bot" in commit_calls[0]
    assert "user.email=bot@example.com" in commit_calls[0]


async def test_commit_all_multiline_message_is_single_argv(mocker):
    """The multi-line PR-closing message travels as ONE argv element."""
    message = (
        "feat: Verify LICENSE file follows standard conventions\n\n"
        "Closes #173\n\n"
        "Co-Authored-By: swarm-dev-agent <agent@swarm-bots.local>"
    )
    commit_calls = []

    async def fake_subprocess(*args, **kwargs):
        proc = AsyncMock()
        proc.returncode = 0
        if args[1] == "status":
            proc.communicate = AsyncMock(return_value=(b"M file.py", b""))
        else:
            proc.communicate = AsyncMock(return_value=(b"", b""))
        if "commit" in args:
            commit_calls.append(args)
        return proc

    mocker.patch("asyncio.create_subprocess_exec", side_effect=fake_subprocess)
    await commit_all("/tmp/repo", message)

    args = commit_calls[0]
    assert args[args.index("-m") + 1] == message


async def test_run_git_timeout_kills_and_raises(mocker):
    """A git command hanging (e.g. credential prompt) is killed, not awaited forever."""
    import asyncio as _asyncio

    proc = AsyncMock()
    proc.returncode = None

    async def hang():
        await _asyncio.sleep(30)

    proc.communicate = hang
    proc.kill = lambda: None
    mocker.patch("asyncio.create_subprocess_exec", return_value=proc)

    with pytest.raises(RuntimeError, match="timed out"):
        await _run_git("clone", "https://example.com/r.git", timeout=0.05)


async def test_run_git_disables_credential_prompts(mock_subprocess):
    import asyncio

    await _run_git("fetch")
    kwargs = asyncio.create_subprocess_exec.call_args.kwargs
    assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert "BatchMode=yes" in kwargs["env"]["GIT_SSH_COMMAND"]


async def test_commit_all_real_repo_without_identity(tmp_path, monkeypatch):
    """Prod repro (cycle adf70608e595): container git has no identity configured.

    ``user.useConfigOnly=true`` makes git refuse to guess from the OS user,
    which is exactly the 'Author identity unknown' rc=128 seen in prod.
    The explicit -c identity flags in commit_all must make the commit pass.
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    monkeypatch.delenv("SWARM_GIT_USER_NAME", raising=False)
    monkeypatch.delenv("SWARM_GIT_USER_EMAIL", raising=False)

    repo = tmp_path / "repo"
    repo.mkdir()
    await _run_git("init", "-q", cwd=str(repo))
    await _run_git("config", "user.useConfigOnly", "true", cwd=str(repo))
    (repo / "f.txt").write_text("x\n")

    # The exact multi-line message shape that failed in prod
    message = (
        "feat: Verify LICENSE file follows standard conventions\n\n"
        "Closes #173\n\n"
        "Co-Authored-By: swarm-dev-agent <agent@swarm-bots.local>"
    )
    committed = await commit_all(str(repo), message)
    assert committed is True

    body = await _run_git("log", "-1", "--pretty=%B", cwd=str(repo))
    author = await _run_git("log", "-1", "--pretty=%an <%ae>", cwd=str(repo))
    assert "Closes #173" in body
    assert author == "TheSwarm Dev Agent <swarm-dev@jrec.fr>"


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
