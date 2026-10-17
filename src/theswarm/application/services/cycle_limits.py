"""Settings → Cycles: how many cycles run at once, in all and per project.

The owner (2026-10-13): "le nombre de cycles max et par projet doivent être
configurables via l'interface". The numbers are read by the gate every
cycle passes (`theswarm.cycle_gate`) from a snapshot kept here — the gate is
synchronous and asks on every arrival and every end — and a change lets in
at once whoever fits now.
"""

from __future__ import annotations

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

    async def save(self, in_all: int | None, per_repo: dict[str, int | None], *, by: str = "") -> None:
        """Validate everything first, then write; None is the default."""
        if in_all is not None and not 1 <= in_all <= MAX_IN_ALL:
            raise CycleLimitsError(f"In all: between 1 and {MAX_IN_ALL}, not {in_all}.")
        for repo, value in per_repo.items():
            if "/" not in repo:
                raise CycleLimitsError(f"{repo!r} is not a repository.")
            if value is not None and not 1 <= value <= MAX_PER_REPO:
                raise CycleLimitsError(f"{repo}: between 1 and {MAX_PER_REPO}, not {value}.")
        await self._repo.put(IN_ALL, in_all, by)
        for repo, value in per_repo.items():
            await self._repo.put(repo, None if value == 1 else value, by)
        await self.refresh()
        from theswarm.cycle_gate import set_cycle_limits

        set_cycle_limits(self)  # whoever fits now starts
