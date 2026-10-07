"""Proposals (D3): DevOps asks, the owner decides, the command runs once.

`raise_from` turns the findings that call for a hand on a machine into
proposals — one open proposal per kind and host, never a second while
the first waits. `approve` runs the proposal's command over the host's
ssh (the same ambient keys D1 reads with) and keeps what came back;
`refuse` keeps the owner's no. Nothing here runs without an approval row.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable

from theswarm.agents.devops import BAD, Finding
from theswarm.domain.ops.proposals import KINDS, Proposal

log = logging.getLogger(__name__)

_SLOT_RE = re.compile(r"\b(slot\d+)\b")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def proposals_for(findings: tuple[Finding, ...] | list[Finding], stack: dict, facts: dict | None = None) -> list[Proposal]:
    """The proposals a report's bad findings call for, with their exact command."""
    hosts = {h.get("name", ""): h for h in stack.get("hosts", []) or []}
    deploy = stack.get("deploy") or {}
    facts = facts or {}
    out: list[Proposal] = []
    for f in findings:
        if f.status != BAD:
            continue
        if f.key == "ci_slot" and "stale" in f.detail:
            host_name = next((n for n in hosts if n and n in f.detail), next(iter(hosts), ""))
            host = hosts.get(host_name, {})
            slot = (_SLOT_RE.search(f.detail) or [None, "slot1"])[1]
            kind = KINDS["clear_slot"]
            out.append(Proposal(
                id=uuid.uuid4().hex[:12], kind="clear_slot", host=host_name,
                title=f"{kind['label']} {slot} on {host_name}", why=f"{f.detail} — {kind['why']}",
                command=kind["command"].format(slot_dir=host.get("ci_slot_dir", "/srv/gh-runner-work/ci-slots"), slot=slot,
                                               sudo="" if host.get("sudo") is False else "sudo "),
                finding_key=f.key,
            ))
        elif f.key == "runners":
            host_name = next(iter(hosts), "")
            service = next((c.get("runner_service", "") for c in stack.get("ci", []) or [] if c.get("runner_service")), "")
            if not service:
                continue
            kind = KINDS["restart_runner"]
            out.append(Proposal(
                id=uuid.uuid4().hex[:12], kind="restart_runner", host=host_name,
                title=f"{kind['label']} {service} on {host_name}", why=f"{f.detail} — {kind['why']}",
                command=kind["command"].format(service=service), finding_key=f.key,
            ))
        elif f.key == "deploy_watch" and deploy.get("service") and stack.get("registry") and facts.get("main_sha"):
            host_name = next(iter(hosts), "")
            kind = KINDS["redeploy"]
            out.append(Proposal(
                id=uuid.uuid4().hex[:12], kind="redeploy", host=host_name,
                title=f"{kind['label']} on {host_name}", why=f"{f.detail} — {kind['why']}",
                command=kind["command"].format(registry=stack["registry"], main_sha=facts["main_sha"], service=deploy["service"]),
                finding_key=f.key,
            ))
    return out


class ProposalService:
    def __init__(self, proposals, stack: dict, runner: Callable[[dict, str], Awaitable[str]] | None = None) -> None:
        self._proposals = proposals
        self._stack = stack
        self._runner = runner

    async def raise_from(self, findings, facts: dict | None = None) -> list[Proposal]:
        """New proposals for the findings; one open proposal per kind and host."""
        open_keys = {(p.kind, p.host) for p in await self._proposals.list_open()}
        raised = []
        for proposal in proposals_for(findings, self._stack, facts):
            if (proposal.kind, proposal.host) in open_keys:
                continue
            await self._proposals.save(proposal)
            open_keys.add((proposal.kind, proposal.host))
            raised.append(proposal)
            log.info("DevOps proposes: %s — %s", proposal.title, proposal.command)
        return raised

    async def open(self) -> list[Proposal]:
        return await self._proposals.list_open()

    async def recent(self, limit: int = 20) -> list[Proposal]:
        return await self._proposals.list_recent(limit)

    async def refuse(self, proposal_id: str, by: str = "owner") -> Proposal | None:
        proposal = await self._proposals.get(proposal_id)
        if proposal is None:
            return None
        refused = proposal.refused(by)
        await self._proposals.save(refused)
        return refused

    async def approve(self, proposal_id: str, by: str = "owner") -> Proposal | None:
        """The owner's yes: the command runs on the host now, and its answer is kept."""
        proposal = await self._proposals.get(proposal_id)
        if proposal is None:
            return None
        approved = proposal.approved(by)
        if approved is proposal:  # not proposed any more
            return proposal
        await self._proposals.save(approved)
        host = next((h for h in self._stack.get("hosts", []) or [] if h.get("name") == proposal.host), None)
        if host is None or self._runner is None:
            done = approved.ran(f"not run: {proposal.host or 'the host'} is not declared or not reachable from here", ok=False)
        else:
            try:
                output = await self._runner(host, proposal.command)
                done = approved.ran(output or "done, nothing said", ok=True)
            except Exception as exc:  # noqa: BLE001 — the answer is the record
                done = approved.ran(f"failed: {str(exc)[:300]}", ok=False)
        await self._proposals.save(done)
        log.warning("DevOps proposal %s %s by %s: %s", proposal.title, done.status, by, done.result[:120])
        return done
