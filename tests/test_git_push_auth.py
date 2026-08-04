"""git push must carry credentials, and they must never leak.

Prod repro (cycle b35b55ef832f): once the dev loop finally reached
``open_pull_request``, the push died with ``could not read Username for
'https://github.com': terminal prompts disabled``. The clone URL carries no
credentials, so the push never had any — before prompts were disabled it
blocked on git's username prompt until the phase timeout, which is why
every April cycle opened zero PRs.
"""

from __future__ import annotations

import base64

from unittest.mock import AsyncMock

import pytest

from theswarm.tools.git import _auth_args, _run_git, clone_repo, push_branch, redact

TOKEN = "ghp_secrettokenvalue123"
EXPECTED_BASIC = base64.b64encode(f"x-access-token:{TOKEN}".encode()).decode()


@pytest.fixture()
def mock_subprocess(mocker):
    proc = AsyncMock()
    proc.returncode = 0
    proc.communicate = AsyncMock(return_value=(b"", b""))
    mocker.patch("asyncio.create_subprocess_exec", return_value=proc)
    return proc


# ── _auth_args ─────────────────────────────────────────────────────────


def test_auth_args_build_basic_header(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    args = _auth_args()
    assert args[0] == "-c"
    assert args[1] == (
        f"http.https://github.com/.extraheader=AUTHORIZATION: basic {EXPECTED_BASIC}"
    )


def test_auth_args_empty_without_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    assert _auth_args() == []


# ── push ───────────────────────────────────────────────────────────────


async def test_push_carries_credentials(mock_subprocess, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    import asyncio

    await push_branch("/tmp/repo", "feat/x")

    args = asyncio.create_subprocess_exec.call_args.args
    assert "-c" in args
    assert any("extraheader=AUTHORIZATION: basic" in a for a in args)
    # The -c flag must precede the subcommand, or git rejects it
    assert args.index("-c") < args.index("push")


async def test_clone_carries_credentials(mock_subprocess, mocker, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    mocker.patch("os.path.isdir", return_value=False)
    mocker.patch("os.makedirs")
    import asyncio

    await clone_repo("https://github.com/o/r.git", "/tmp/repo")

    args = asyncio.create_subprocess_exec.call_args.args
    assert any("extraheader=AUTHORIZATION: basic" in a for a in args)


async def test_push_without_token_sends_no_auth_flag(mock_subprocess, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    import asyncio

    await push_branch("/tmp/repo", "feat/x")

    assert asyncio.create_subprocess_exec.call_args.args == (
        "git", "push", "-u", "origin", "feat/x",
    )


# ── redaction ──────────────────────────────────────────────────────────


def test_redact_masks_basic_header(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    text = f"http.https://github.com/.extraheader=AUTHORIZATION: basic {EXPECTED_BASIC}"
    assert EXPECTED_BASIC not in redact(text)
    assert "***" in redact(text)


def test_redact_masks_raw_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    assert TOKEN not in redact(f"remote: https://{TOKEN}@github.com/o/r")


async def test_failure_message_does_not_leak_credentials(mocker, monkeypatch):
    """A failing authenticated push must not print the token in its exception."""
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    proc = AsyncMock()
    proc.returncode = 128
    proc.communicate = AsyncMock(return_value=(b"", f"denied for {TOKEN}".encode()))
    mocker.patch("asyncio.create_subprocess_exec", return_value=proc)

    with pytest.raises(RuntimeError) as excinfo:
        await push_branch("/tmp/repo", "feat/x")

    message = str(excinfo.value)
    assert TOKEN not in message
    assert EXPECTED_BASIC not in message


async def test_timeout_message_does_not_leak_credentials(mocker, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    import asyncio as _asyncio

    proc = AsyncMock()
    proc.returncode = None

    async def hang():
        await _asyncio.sleep(30)

    proc.communicate = hang
    proc.kill = lambda: None
    mocker.patch("asyncio.create_subprocess_exec", return_value=proc)

    with pytest.raises(RuntimeError) as excinfo:
        await _run_git(*_auth_args(), "push", timeout=0.05)

    assert TOKEN not in str(excinfo.value)
    assert EXPECTED_BASIC not in str(excinfo.value)
