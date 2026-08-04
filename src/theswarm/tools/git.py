"""Local git operations for the SWARM MVP Dev agent."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import shutil

log = logging.getLogger(__name__)

# Default committer identity for agent commits (matches the GIT_AUTHOR/
# COMMITTER values in docker-compose.yml). In containers there is no global
# git config, so `git commit` fails with rc=128 "Author identity unknown"
# unless the identity is supplied explicitly.
DEFAULT_GIT_USER_NAME = "TheSwarm Dev Agent"
DEFAULT_GIT_USER_EMAIL = "swarm-dev@jrec.fr"

# Hard cap on any single git command. Without it, a clone/push waiting on a
# credential prompt hangs forever — outside the cycle's phase timeouts.
GIT_COMMAND_TIMEOUT = 300


async def _run_git(
    *args: str,
    cwd: str | None = None,
    check: bool = True,
    timeout: float = GIT_COMMAND_TIMEOUT,
) -> str:
    """Run a git command and return stdout."""
    env = {
        **os.environ,
        # Never prompt for credentials or SSH host confirmation — fail instead.
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_SSH_COMMAND": os.environ.get("GIT_SSH_COMMAND", "ssh -oBatchMode=yes"),
    }
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
        cwd=cwd,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise RuntimeError(
            f"git {redact(' '.join(args))} timed out after {timeout:.0f}s"
        ) from None
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {redact(' '.join(args))} failed (rc={proc.returncode}): "
            f"{redact(stderr.decode())[:500]}"
        )
    return stdout.decode().strip()


_EXTRAHEADER_RE = re.compile(r"(extraheader=AUTHORIZATION: basic )\S+", re.IGNORECASE)


def redact(text: str) -> str:
    """Strip credentials from anything headed for a log or an exception."""
    cleaned = _EXTRAHEADER_RE.sub(r"\1***", text)
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        cleaned = cleaned.replace(token, "***")
    return cleaned


def _identity_args() -> list[str]:
    """Explicit committer identity flags, overridable via env."""
    name = os.environ.get("SWARM_GIT_USER_NAME", DEFAULT_GIT_USER_NAME)
    email = os.environ.get("SWARM_GIT_USER_EMAIL", DEFAULT_GIT_USER_EMAIL)
    return ["-c", f"user.name={name}", "-c", f"user.email={email}"]


def _auth_args() -> list[str]:
    """GitHub credentials for network operations over HTTPS.

    Passed per command with ``-c`` rather than baked into the remote URL, so
    the token never lands in the workspace's ``.git/config`` where later
    commands (and anything else in the container) could read it back.

    Without this, ``git push`` has no credentials at all: it used to block on
    git's username prompt until the phase timeout killed it, which is why
    every April cycle opened zero PRs. With prompts disabled it now fails
    fast instead — this supplies the credentials it was always missing.
    """
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        return []
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return ["-c", f"http.https://github.com/.extraheader=AUTHORIZATION: basic {basic}"]


async def clone_repo(repo_url: str, dest: str) -> str:
    """Clone a repo to dest. If dest already exists, pull instead."""
    if os.path.isdir(os.path.join(dest, ".git")):
        log.info("Repo already cloned at %s — pulling latest", dest)
        await _run_git("checkout", "main", cwd=dest, check=False)
        await _run_git(*_auth_args(), "pull", "--ff-only", cwd=dest, check=False)
        return dest

    log.info("Cloning %s → %s", repo_url, dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    await _run_git(*_auth_args(), "clone", repo_url, dest)
    return dest


async def create_branch(workdir: str, branch_name: str, base: str = "main") -> None:
    """Create and checkout a new branch from base."""
    await _run_git("checkout", base, cwd=workdir)
    await _run_git(*_auth_args(), "pull", "--ff-only", cwd=workdir, check=False)
    await _run_git("checkout", "-b", branch_name, cwd=workdir)
    log.info("Created branch %s from %s", branch_name, base)


async def commit_all(workdir: str, message: str) -> bool:
    """Stage all changes and commit. Returns True if there was something to commit."""
    await _run_git("add", "-A", cwd=workdir)

    # Check if there's anything to commit
    status = await _run_git("status", "--porcelain", cwd=workdir)
    if not status:
        log.info("Nothing to commit")
        return False

    try:
        await _run_git(*_identity_args(), "commit", "-m", message, cwd=workdir)
    except RuntimeError as exc:
        if "Author identity unknown" not in str(exc) and "user.email" not in str(exc):
            raise
        # The -c flags should make this unreachable; if git still refuses,
        # persist a repo-local identity and retry once.
        log.warning("No git identity in environment — setting repo-local fallback")
        name = os.environ.get("SWARM_GIT_USER_NAME", DEFAULT_GIT_USER_NAME)
        email = os.environ.get("SWARM_GIT_USER_EMAIL", DEFAULT_GIT_USER_EMAIL)
        await _run_git("config", "user.name", name, cwd=workdir)
        await _run_git("config", "user.email", email, cwd=workdir)
        await _run_git("commit", "-m", message, cwd=workdir)
    log.info("Committed: %s", message)
    return True


async def push_branch(workdir: str, branch_name: str) -> None:
    """Push branch to origin."""
    await _run_git(*_auth_args(), "push", "-u", "origin", branch_name, cwd=workdir)
    log.info("Pushed branch %s", branch_name)


async def get_diff_stat(workdir: str) -> str:
    """Get a compact diff stat of current changes vs main."""
    return await _run_git("diff", "--stat", "main", cwd=workdir, check=False)


async def cleanup_workspace(workdir: str) -> None:
    """Remove the workspace directory."""
    if os.path.isdir(workdir):
        shutil.rmtree(workdir)
        log.info("Cleaned up workspace: %s", workdir)
