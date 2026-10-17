"""The TechLead's merge watch: approved work lands without waiting for a cycle.

The review pass merges an approved PR whose CI is green; one whose CI is
still running is left open, and nothing came back for it until the next
cycle on that repository — which may never come. espace-client#499 was
approved on 2026-10-08 five minutes before its CI went green and sat in
review for days; concert-tour-app#307, refused past the cap, had sat there
since 2026-09-29 "for a person" (owner, 2026-10-11: "les cartes restent
bloquées in review indéfiniment").

Every `SWARM_MERGE_WATCH_SECONDS` (300; 0 is off) the watch goes over each
registered repository no cycle is running on, and reads the verdicts the
review left on the heads (`theswarm/review` — no Claude call):

- approved: merged once the PR holds main and its CI is green — main is
  merged in first when it moved on (`techlead.bring_up_to_date`), a red CI
  goes back to the Dev, a conflict too; on the swarm's own repository only
  its own branches, and only while no cycle runs anywhere (a merge there
  redeploys this service);
- changes requested on a task the cap put in review: given up
  (`techlead.abandon_task`), PR and task closed with the reason.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_SWEEP_SECONDS = 300


def sweep_seconds() -> int:
    raw = os.environ.get("SWARM_MERGE_WATCH_SECONDS", "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_SWEEP_SECONDS
    except ValueError:
        return DEFAULT_SWEEP_SECONDS


@dataclass(frozen=True)
class Sweep:
    """What one pass did on one repository."""

    repo: str
    merged: tuple[int, ...] = ()
    updating: tuple[int, ...] = ()
    waiting: tuple[int, ...] = ()
    sent_back: tuple[int, ...] = ()
    given_up: tuple[int, ...] = ()
    skipped: str = ""

    @property
    def acted(self) -> bool:
        return bool(self.merged or self.updating or self.sent_back or self.given_up)


def _client(repo: str):
    from theswarm.tools.github import GitHubClient

    return GitHubClient(repo)


class MergeWatch:
    def __init__(self, project_repo, *, client_for=_client, interval: int | None = None) -> None:
        self._projects = project_repo
        self._client_for = client_for
        self._interval = sweep_seconds() if interval is None else interval

    async def repos(self) -> list[str]:
        try:
            projects = await self._projects.list_all()
        except Exception:  # noqa: BLE001 — no list, no sweep this turn
            log.exception("Merge watch: listing the projects failed")
            return []
        return sorted({str(p.repo) for p in projects if "/" in str(p.repo)})

    async def sweep(self) -> list[Sweep]:
        done = []
        for repo in await self.repos():
            try:
                done.append(await self.sweep_repo(repo))
            except Exception:  # noqa: BLE001 — one repository never stops the others
                log.exception("Merge watch: the sweep of %s failed", repo)
        return done

    async def sweep_repo(self, repo: str) -> Sweep:
        from theswarm import cycle
        from theswarm.agents.techlead import SELF_REPO

        gate = cycle.cycle_gate()
        if gate.busy(repo):
            return Sweep(repo, skipped="a cycle is running on it")
        if repo == SELF_REPO and gate.busy():
            return Sweep(repo, skipped="a cycle is running, and a merge here redeploys")
        if not gate.try_hold_alone(repo):  # a cycle that starts meanwhile waits a few seconds
            return Sweep(repo, skipped="a cycle is about to start on it")
        try:
            github = await asyncio.to_thread(self._client_for, repo)
            outcome = await _sweep(github, repo, self_repo=repo == SELF_REPO)
        finally:
            gate.release_alone(repo)
        if outcome.acted:
            log.info("Merge watch on %s: merged %s, main merged in %s, sent back %s, given up %s",
                     repo, list(outcome.merged), list(outcome.updating),
                     list(outcome.sent_back), list(outcome.given_up))
        return outcome

    async def run_loop(self) -> None:
        """Sweep on the cadence; lives as long as the server."""
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.sweep()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("Merge watch: a turn failed")


async def _sweep(github, repo: str, *, self_repo: bool) -> Sweep:
    from theswarm.agents import techlead

    approved: list[dict] = []
    given_up: list[int] = []
    for pr in await github.get_open_prs():
        verdict = await techlead._earlier_verdict(github, pr)
        if verdict is None:
            continue  # never reviewed: the next cycle's review pass reads it
        if verdict["decision"] == "APPROVE":
            approved.append(verdict)
        elif verdict["decision"] == "REQUEST_CHANGES":
            task = techlead._task_of_pr(pr)
            if task is not None and await _parked(github, task):
                await techlead.abandon_task(
                    github, pr, task, "Changes were requested past the cap", verdict.get("summary", ""))
                given_up.append(pr["number"])
    if not approved:
        return Sweep(repo, given_up=tuple(given_up))

    result = await techlead.merge_approved_prs(
        {"github": github, "github_repo": repo, "reviews": approved}, ci_wait_seconds=0,
    )
    merged = list(result.get("merged_prs", []))
    sent_back = [*result.get("ci_red_prs", []), *result.get("conflicted_prs", [])]
    held = list(result.get("held_prs", []))
    if self_repo and held:
        from theswarm import cycle

        merged += await cycle._merge_held_prs(github, held, None, earlier=set(held), ci_wait_seconds=0,
                                              sent_back=sent_back)
    numbers = [r["pr_number"] for r in approved]
    left = [n for n in numbers if n not in merged and n not in sent_back]
    updating = [n for n in left if n in result.get("updating_prs", [])]
    return Sweep(repo, merged=tuple(merged), updating=tuple(updating),
                 waiting=tuple(n for n in left if n not in updating),
                 sent_back=tuple(sent_back), given_up=tuple(given_up))


async def _parked(github, task: int) -> bool:
    """The cap put this task in review (`status:review`, still open)."""
    from theswarm.tools.github import issue_status

    issue = await github.get_issue(task)
    return bool(issue) and issue.get("state") == "open" and issue_status(issue) == "review"
