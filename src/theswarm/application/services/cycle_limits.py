"""Settings → Cycles: how many cycles run at once, in all and per project.

The owner (2026-10-13): "le nombre de cycles max et par projet doivent être
configurables via l'interface". The numbers are read by the gate every
cycle passes (`theswarm.cycle_gate`) from a snapshot kept here — the gate is
synchronous and asks on every arrival and every end — and a change lets in
at once whoever fits now.
"""

from __future__ import annotations

from theswarm.claude_window import DEFAULT_SHARE, MIN_SHARE, SHARE_SCOPE, env_share
from theswarm.cycle_gate import MAX_IN_ALL, MAX_PER_REPO

IN_ALL = "*"


class CycleLimitsError(ValueError):
    pass


class CycleLimitsService:
    def __init__(self, repo) -> None:
        self._repo = repo
        self._snapshot: dict[str, int] = {}

    async def refresh(self) -> dict[str, int]:
        self._snapshot = dict(await self._repo.all())
        return dict(self._snapshot)

    def global_max(self) -> int | None:
        return self._snapshot.get(IN_ALL)

    def repo_max(self, repo: str) -> int | None:
        return self._snapshot.get(repo)

    def claude_share(self) -> int | None:
        """The percent of Claude's window the swarm may use (A1), None for all of it."""
        return self._snapshot.get(SHARE_SCOPE)

    async def save(self, in_all: int | None, per_repo: dict[str, int | None], *, by: str = "",
                   claude_share: int | None | object = ...) -> None:
        """Validate everything first, then write; None is the default. A
        `claude_share` left out keeps the one saved."""
        if in_all is not None and not 1 <= in_all <= MAX_IN_ALL:
            raise CycleLimitsError(f"In all: between 1 and {MAX_IN_ALL}, not {in_all}.")
        if claude_share is not ... and claude_share is not None and not MIN_SHARE <= claude_share <= DEFAULT_SHARE:
            raise CycleLimitsError(f"Claude's window: between {MIN_SHARE} and {DEFAULT_SHARE}%, not {claude_share}.")
        for repo, value in per_repo.items():
            if "/" not in repo:
                raise CycleLimitsError(f"{repo!r} is not a repository.")
            if value is not None and not 1 <= value <= MAX_PER_REPO:
                raise CycleLimitsError(f"{repo}: between 1 and {MAX_PER_REPO}, not {value}.")
        await self._repo.put(IN_ALL, in_all, by)
        if claude_share is not ...:
            # The instance's default is no row, as for "In all"
            await self._repo.put(SHARE_SCOPE, None if claude_share in (None, env_share()) else claude_share, by)
        for repo, value in per_repo.items():
            await self._repo.put(repo, None if value == 1 else value, by)
        await self.refresh()
        from theswarm.cycle_gate import set_cycle_limits

        set_cycle_limits(self)  # whoever fits now starts
