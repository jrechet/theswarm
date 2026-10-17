"""Who may start: the one gate every cycle passes, whatever started it.

The rules, all checked together, in the order the cycles arrived:

- **In all**, at most `max_concurrent_cycles()` cycles run at once — the box
  and the one subscription window (`SWARM_MAX_CONCURRENT_CYCLES`, or the
  owner's number in Settings → Cycles).
- **Per repository**, at most `repo_max_cycles(repo)` — 1 unless the owner
  raised it. Above 1 each cycle works in a clone of its own
  (`cycle_workspace`): one directory per repository was the reason for one
  cycle at a time — a cycle resets, cleans and deletes it as if it were
  alone, and two of them erased each other's branches (16f3b8af2cca vs
  2878898cc504).
- **Never two cycles on one feature** (the same pinned issue): they would
  build the same tasks on the same branches.
- **A cycle without a feature runs alone on its repository**: it picks from
  the whole backlog, and could take the tasks another cycle is building.

A cycle that does not fit waits; when one ends — or the owner raises a
limit — every waiting cycle that fits now starts, the oldest first. The
owner asked (2026-10-13): "le nombre de cycles max et par projet doivent
être configurables via l'interface".
"""

from __future__ import annotations

import asyncio
import os
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

DEFAULT_MAX_CONCURRENT_CYCLES = 1
DEFAULT_REPO_MAX_CYCLES = 1
# Bounds the settings page offers: the container is sized for about two
# cycles (4 GB, docker-compose.yml), each with its Dev pair and QA lanes.
MAX_IN_ALL = 6
MAX_PER_REPO = 4

# The owner's numbers (Settings → Cycles), set by the server; None reads
# the environment as before.
_LIMITS = None


def set_cycle_limits(limits) -> None:
    """`CycleLimitsService`, or None for the environment alone (CLI, tests)."""
    global _LIMITS
    _LIMITS = limits
    for gate in _GATES.values():
        gate.limits_changed()


def env_max_concurrent_cycles() -> int:
    raw = os.environ.get("SWARM_MAX_CONCURRENT_CYCLES", "").strip()
    try:
        return max(1, int(raw)) if raw else DEFAULT_MAX_CONCURRENT_CYCLES
    except ValueError:
        return DEFAULT_MAX_CONCURRENT_CYCLES


def max_concurrent_cycles() -> int:
    """How many cycles may run at once, all repositories together."""
    if _LIMITS is not None:
        chosen = _LIMITS.global_max()
        if chosen:
            return max(1, int(chosen))
    return env_max_concurrent_cycles()


def repo_max_cycles(repo: str) -> int:
    """How many cycles may run at once on `repo` (1 unless the owner raised it)."""
    if _LIMITS is not None:
        chosen = _LIMITS.repo_max(repo)
        if chosen:
            return max(1, int(chosen))
    return DEFAULT_REPO_MAX_CYCLES


@dataclass
class _Entry:
    cycle_id: str
    repo: str
    issue: int | None
    admitted: asyncio.Event = field(default_factory=asyncio.Event)


class CycleGate:
    def __init__(self) -> None:
        self._running: dict[str, _Entry] = {}
        self._waiting: list[_Entry] = []

    # ── what the pages and the merge watch read ──
    def running_on(self, repo: str) -> list[str]:
        return [e.cycle_id for e in self._running.values() if e.repo == repo]

    def busy(self, repo: str | None = None) -> bool:
        return any(repo is None or e.repo == repo for e in self._running.values())

    def why_waiting(self, cycle_id: str) -> str:
        """`repo` (its repository is full or must be alone), `feature` (its
        feature is being built), `slot` (the box is full), '' when not waiting."""
        entry = next((e for e in self._waiting if e.cycle_id == cycle_id), None)
        return self._blocker(entry) if entry is not None else ""

    # ── the rules ──
    def _blocker(self, entry: _Entry) -> str:
        mine = [e for e in self._running.values() if e.repo == entry.repo]
        if entry.issue is not None and any(e.issue == entry.issue for e in mine):
            return "feature"
        if mine and (entry.issue is None or any(e.issue is None for e in mine)):
            return "repo"
        if len(mine) >= repo_max_cycles(entry.repo):
            return "repo"
        if len(self._running) >= max_concurrent_cycles():
            return "slot"
        return ""

    def _admit(self) -> None:
        # The oldest first; a cycle never passes an older one its repository
        # holds back (a cycle without a feature waiting to run alone would
        # otherwise wait for ever behind a stream of Plays). One blocked on
        # its own feature holds nobody back.
        held_back: set[str] = set()
        for entry in list(self._waiting):
            if entry.repo in held_back:
                continue
            why = self._blocker(entry)
            if not why:
                self._waiting.remove(entry)
                self._running[entry.cycle_id] = entry
                entry.admitted.set()
            elif why == "repo":
                held_back.add(entry.repo)

    def limits_changed(self) -> None:
        """The owner raised (or lowered) a limit: whoever fits now starts."""
        self._admit()

    def fits_now(self, repo: str, issue: int | None) -> bool:
        """Would a cycle arriving now start at once (nobody waiting ahead of it)?"""
        probe = _Entry("", repo, issue)
        return not self._waiting and not self._blocker(probe)

    @asynccontextmanager
    async def hold(self, cycle_id: str, repo: str, issue: int | None):
        """Wait for this cycle's turn, then hold its place while it runs."""
        entry = _Entry(cycle_id, repo, issue)
        self._waiting.append(entry)
        self._admit()
        try:
            await entry.admitted.wait()
        except BaseException:
            if entry in self._waiting:
                self._waiting.remove(entry)
            elif self._running.get(cycle_id) is entry:
                del self._running[cycle_id]
                self._admit()
            raise
        try:
            yield
        finally:
            if self._running.get(cycle_id) is entry:
                del self._running[cycle_id]
            self._admit()

    def try_hold_alone(self, repo: str) -> bool:
        """Hold `repo` at once as a cycle without a feature would (nothing
        else running or waiting there), or say no — the merge watch's sweep."""
        probe = _Entry(f"sweep:{repo}", repo, None)
        if any(e.repo == repo for e in self._waiting) or self._blocker(probe) in ("repo", "feature"):
            return False
        self._running[probe.cycle_id] = probe
        return True

    def release_alone(self, repo: str) -> None:
        self._running.pop(f"sweep:{repo}", None)
        self._admit()


_GATES: dict[int, CycleGate] = {}


def cycle_gate() -> CycleGate:
    """The gate of the running event loop (one per loop, like the locks were)."""
    loop = asyncio.get_running_loop()
    gate = _GATES.get(id(loop))
    if gate is None:
        _GATES.clear()  # a loop that no longer runs holds nothing
        gate = _GATES[id(loop)] = CycleGate()
    return gate


def cycle_workspace(base_dir: str, repo: str, thread_id: str) -> str:
    """Where a cycle works: the repository's directory when it runs alone
    there, a clone of its own (`<repo>@<thread>`) when the owner allows more
    than one — the thread id, so a continuation finds its origin's tree."""
    if repo_max_cycles(repo) <= 1 or not thread_id:
        return base_dir
    return f"{base_dir.rstrip(os.sep)}@{thread_id}"


_CYCLE_SUFFIX = re.compile(r"@[0-9a-f]{12}(?=/|$)")


def floor_key(workdir: str) -> str:
    """A workspace's repository-level key (`<repo>@<thread>` → `<repo>`): what
    is learned about a repository outlives one cycle's clone."""
    return _CYCLE_SUFFIX.sub("", workdir or "")
