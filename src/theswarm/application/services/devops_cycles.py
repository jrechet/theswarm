"""DevOps in the cycle — the plan's fifth station, "only in the cycles where
it acts" (docs/plans/2026-10-v3-one-product.md, "In the product").

DevOps acts twice in a cycle, and says so on the bus as the other agents do
(`AgentActivity`, agent `devops`, kept by the cycle event store, read by the
theater's feed and its DevOps station):

- **the preflight** — before the cycle starts, its go (and what it read) or
  its no-go (and why the cycle was not started);
- **the deploy watch** — on the swarm's own repository, when the cycle
  merged to main: the new build will replace this server, and DevOps
  watches it land. The watch is closed by a later DevOps report — usually
  the new container's first one: *landed* when this server's build is
  main's head and is not the build that was running when the watch began,
  *late* when the report's deploy watch finding is bad (the deploy failed,
  or main has not reached the box in 45 minutes). Each once.

Telling never costs the cycle anything: a publish that fails is logged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

from theswarm.domain.cycles.events import AgentActivity
from theswarm.domain.cycles.value_objects import CycleId, CycleStatus

log = logging.getLogger(__name__)

AGENT = "devops"
PREFLIGHT, PREFLIGHT_NOGO = "preflight", "preflight_nogo"
DEPLOY_WATCH, DEPLOY_LANDED, DEPLOY_LATE = "deploy_watch", "deploy_landed", "deploy_late"
ACTS = (PREFLIGHT, PREFLIGHT_NOGO, DEPLOY_WATCH, DEPLOY_LANDED, DEPLOY_LATE)
RESOLVE_WINDOW = timedelta(days=2)  # a watch older than this is left alone

_WORDS = {"ok": "fine", "warn": "to look at", "bad": "bad", "unknown": "not read"}
_PREFLIGHT_KEYS = ("claude", "disk_here", "runners", "ci_slot")


def preflight_words(answer: Any) -> str:
    """The preflight as one sentence: what it read when it is go, why when it is not."""
    if not answer.go:
        return "Preflight: no-go, the cycle is not started — " + "; ".join(answer.reasons)
    findings = {f.key: f for f in getattr(answer.report, "findings", ())}
    read = [f"{findings[k].label} {_WORDS.get(findings[k].status, findings[k].status)}"
            for k in _PREFLIGHT_KEYS if k in findings]
    return "Preflight: go" + (" — " + " · ".join(read) if read else "")


def preflight_activity(cycle_id: str, project_id: str, answer: Any) -> AgentActivity:
    return AgentActivity(
        cycle_id=CycleId(cycle_id), project_id=project_id, agent=AGENT,
        action=PREFLIGHT if answer.go else PREFLIGHT_NOGO, detail=preflight_words(answer),
        metadata={"go": bool(answer.go), "reasons": list(answer.reasons)},
    )


def deploy_watch_activity(cycle_id: str, project_id: str, merged: list[int] | tuple[int, ...],
                          build_before: str) -> AgentActivity:
    n = len(merged)
    return AgentActivity(
        cycle_id=CycleId(cycle_id), project_id=project_id, agent=AGENT, action=DEPLOY_WATCH,
        detail=(f"Watching the deploy: {n} pull request{'s' if n != 1 else ''} merged to main — "
                "the new build replaces this server"),
        metadata={"merged": list(merged), "build_before": build_before or ""},
    )


async def tell(publish: Callable[[Any], Awaitable[Any]] | None, activity: AgentActivity) -> None:
    """Publish one DevOps act; never the cycle's problem."""
    if publish is None:
        return
    try:
        await publish(activity)
    except Exception:  # noqa: BLE001
        log.exception("DevOps: %s was not told", activity.action)


def _devops_acts(records: list[Any]) -> list[tuple[str, dict]]:
    out = []
    for r in records:
        payload = getattr(r, "payload", {}) or {}
        if getattr(r, "event_type", "") == "AgentActivity" and str(payload.get("agent", "")).strip().lower() == AGENT:
            out.append((str(payload.get("action", "")), payload.get("metadata") or {}))
    return out


async def resolve_deploys(report: Any, cycle_repo: Any, event_store: Any,
                          publish: Callable[[Any], Awaitable[Any]], now: datetime | None = None) -> list[str]:
    """Close the deploy watches a DevOps report can answer; the cycle ids it told about."""
    if cycle_repo is None or event_store is None:
        return []
    now = now or datetime.now(timezone.utc)
    facts = getattr(report, "facts", {}) or {}
    main, build = str(facts.get("main_sha", "") or ""), str(facts.get("build_sha", "") or "")
    landed = bool(main and build and main[:7] == build[:7])
    late = next((f for f in getattr(report, "findings", ()) if f.key == "deploy_watch" and f.status == "bad"), None)
    if not landed and late is None:
        return []
    told: list[str] = []
    for c in await cycle_repo.list_since(now - RESOLVE_WINDOW):
        if c.status != CycleStatus.COMPLETED or not c.prs_merged:
            continue
        acts = _devops_acts(await event_store.list_for_cycle(str(c.id)))
        watch = next((meta for action, meta in acts if action == DEPLOY_WATCH), None)
        done = {action for action, _ in acts}
        if watch is None or DEPLOY_LANDED in done:
            continue
        before = str(watch.get("build_before", "") or "")
        if landed and before[:7] != build[:7]:
            await tell(publish, AgentActivity(
                cycle_id=c.id, project_id=c.project_id, agent=AGENT, action=DEPLOY_LANDED,
                detail=f"The deploy landed: this server runs {build[:7]}, main's head — what the cycle merged is live",
                metadata={"build": build},
            ))
            told.append(str(c.id))
        elif late is not None and DEPLOY_LATE not in done:
            await tell(publish, AgentActivity(
                cycle_id=c.id, project_id=c.project_id, agent=AGENT, action=DEPLOY_LATE,
                detail=f"The deploy has not landed: {late.detail}", metadata={"main": main, "build": build},
            ))
            told.append(str(c.id))
    return told
