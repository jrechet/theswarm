"""One writer at a time per file the swarm keeps on a repository's main.

The agent memory (`AGENT_MEMORY.jsonl`) and the cycle history
(`docs/cycle-history.jsonl`) are read, extended and written back whole
through GitHub's contents API. Two cycles on one repository (or on two, for
the same file name on different repositories this lock is per repository)
each read the same file, each wrote back what they read plus their own —
the second write dropped the first cycle's lines (A1 bis, C4). Both cycles
run in this one process, so a lock per repository and path is the whole
fix: the read and the write happen under it.
"""

from __future__ import annotations

import asyncio

_LOCKS: dict[tuple[int, str, str], asyncio.Lock] = {}


def repo_of(github) -> str:
    """The repository a GitHub client writes to ('' when it does not say)."""
    return str(getattr(github, "repo_name", "") or "")


def file_lock(repo: str, path: str) -> asyncio.Lock:
    """The lock of `path` on `repo`'s main, for the running event loop."""
    loop_id = id(asyncio.get_running_loop())
    key = (loop_id, repo or "", path)
    lock = _LOCKS.get(key)
    if lock is None:
        for stale in [k for k in _LOCKS if k[0] != loop_id]:  # a loop that no longer runs holds nothing
            del _LOCKS[stale]
        lock = _LOCKS[key] = asyncio.Lock()
    return lock
