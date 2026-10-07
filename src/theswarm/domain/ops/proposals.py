"""A proposal — what DevOps asks the owner to let it do (D3).

DevOps reads and diagnoses freely; anything that changes a machine — clear
the CI slot, restart a runner, redeploy — is a proposal: raised from a
finding, approved or refused by the owner with one click, then run and
its result recorded. Nothing runs on its own. Frozen: every change is a
copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone

PROPOSED = "proposed"
APPROVED = "approved"
REFUSED = "refused"
RUN = "run"
FAILED = "failed"
OPEN = (PROPOSED, APPROVED)

# What DevOps may propose, and the exact read-write command each means on
# the host. The command is the proposal's whole power: nothing else runs.
KINDS = {
    "clear_slot": {
        "label": "Clear the CI slot",
        "why": "a slot held past the stale rule queues every job on the box behind a job that is gone",
        "command": "{sudo}rm -rf {slot_dir}/{slot}",
    },
    "restart_runner": {
        "label": "Restart the runner",
        "why": "a runner offline takes every CI job of its repository with it",
        "command": "docker service update --force {service}",
    },
    "redeploy": {
        "label": "Redeploy main",
        "why": "main moved and the box still runs an older build",
        "command": "docker service update --image {registry}:{main_sha} {service}",
    },
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Proposal:
    id: str
    kind: str
    host: str
    title: str
    why: str
    command: str
    finding_key: str = ""
    status: str = PROPOSED
    result: str = ""
    decided_by: str = ""
    created_at: datetime = field(default_factory=_now)
    decided_at: datetime | None = None
    ran_at: datetime | None = None

    @property
    def is_open(self) -> bool:
        return self.status in OPEN

    def approved(self, by: str = "owner", now: datetime | None = None) -> Proposal:
        if self.status != PROPOSED:
            return self
        return replace(self, status=APPROVED, decided_by=by, decided_at=now or _now())

    def refused(self, by: str = "owner", now: datetime | None = None) -> Proposal:
        if self.status != PROPOSED:
            return self
        return replace(self, status=REFUSED, decided_by=by, decided_at=now or _now())

    def ran(self, result: str, ok: bool, now: datetime | None = None) -> Proposal:
        """The command's outcome; only an approved proposal can have run."""
        if self.status != APPROVED:
            return self
        return replace(self, status=RUN if ok else FAILED, result=(result or "").strip()[:2000], ran_at=now or _now())
