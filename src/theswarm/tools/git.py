"""Local git operations for the SWARM MVP Dev agent."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil

log = logging.getLogger(__name__)


async def _run_git(
    *args: str,
    cwd: str | None = None,
    check: bool = True,
) -> str:
    """Run a git command and return stdout."""
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): {stderr.decode()[:500]}"
        )
    return stdout.decode().strip()


async def clone_repo(repo_url: str, dest: str) -> str:
    """Clone a repo to dest. If dest already exists, pull instead."""
    if os.path.isdir(os.path.join(dest, ".git")):
        log.info("Repo already cloned at %s — pulling latest", dest)
        await _run_git("checkout", "main", cwd=dest, check=False)
        await _run_git("pull", "--ff-only", cwd=dest, check=False)
        return dest

    log.info("Cloning %s → %s", repo_url, dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    await _run_git("clone", repo_url, dest)
    return dest


async def create_branch(workdir: str, branch_name: str, base: str = "main") -> None:
    """Create and checkout a new branch from base."""
    await _run_git("checkout", base, cwd=workdir)
    await _run_git("pull", "--ff-only", cwd=workdir, check=False)
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

    await _run_git("commit", "-m", message, cwd=workdir)
    log.info("Committed: %s", message)
    return True


async def push_branch(workdir: str, branch_name: str) -> None:
    """Push branch to origin."""
    await _run_git("push", "-u", "origin", branch_name, cwd=workdir)
    log.info("Pushed branch %s", branch_name)


async def get_diff_stat(workdir: str) -> str:
    """Get a compact diff stat of current changes vs main."""
    return await _run_git("diff", "--stat", "main", cwd=workdir, check=False)


async def cleanup_workspace(workdir: str) -> None:
    """Remove the workspace directory."""
    if os.path.isdir(workdir):
        shutil.rmtree(workdir)
        log.info("Cleaned up workspace: %s", workdir)
