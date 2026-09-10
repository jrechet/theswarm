"""Continue cycles a restart interrupted, instead of losing their work.

Every deploy replaces the container, and the cycle tracker lives in memory,
so a cycle running at that moment dies mid-flight. The pieces to continue it
already existed — ``cycle.py`` writes a checkpoint per phase and
``run_daily_cycle(resume_from=...)`` skips the phases already done — but
nothing ever used them automatically, so hours of PO/TechLead/Dev work were
thrown away on every deploy.

The decision is a pure function so the guards are testable without a
database, a container or a real cycle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

RESUME_TRIGGER = "auto-resume"

# A cycle that crashes on the phase it resumes into would resume forever.
# One automatic continuation per interrupted cycle: if that one dies too,
# the phase itself is the problem and a human should look.
MAX_RESUME_DEPTH = 1

# A restart during a busy period must not launch a herd of cycles at once.
MAX_RESUMES_PER_BOOT = 3


@dataclass(frozen=True)
class ResumePlan:
    """One interrupted cycle worth continuing."""

    cycle_id: str
    repo: str
    resume_from: str
    depth: int

    @property
    def triggered_by(self) -> str:
        return f"{RESUME_TRIGGER}:{self.depth}"

    @property
    def description(self) -> str:
        return f"Resume of {self.cycle_id} from {self.resume_from}"


def resume_depth(triggered_by: str) -> int:
    """How many automatic resumes already led to this cycle."""
    prefix = f"{RESUME_TRIGGER}:"
    if not triggered_by.startswith(prefix):
        return 0
    try:
        return int(triggered_by[len(prefix):])
    except ValueError:
        return 0


def plan_resumes(
    interrupted: list[dict],
    *,
    max_depth: int = MAX_RESUME_DEPTH,
    max_per_boot: int = MAX_RESUMES_PER_BOOT,
) -> list[ResumePlan]:
    """Decide which interrupted cycles to continue, and from where.

    ``interrupted`` items carry ``cycle_id``, ``repo``, ``triggered_by`` and
    ``resume_from`` (the phase after the last good checkpoint, or None when
    the cycle never completed one).
    """
    plans: list[ResumePlan] = []
    for item in interrupted:
        resume_from = item.get("resume_from")
        repo = (item.get("repo") or "").strip()
        cycle_id = item.get("cycle_id") or ""
        if not resume_from or not repo or not cycle_id:
            # Nothing was finished, or we cannot tell which repo to run
            # against: the reap already marked it failed, which is honest.
            continue

        depth = resume_depth(item.get("triggered_by") or "")
        if depth >= max_depth:
            log.info(
                "Cycle %s not resumed: already an automatic resume (depth %d)",
                cycle_id, depth,
            )
            continue

        plans.append(ResumePlan(
            cycle_id=cycle_id, repo=repo,
            resume_from=resume_from, depth=depth + 1,
        ))
        if len(plans) >= max_per_boot:
            break
    return plans


async def collect_interrupted(cycle_repo, checkpoint_repo) -> list[dict]:
    """Read cycles left 'running' by a dead process, with their checkpoints.

    Must run *before* the orphan reap, which flips those rows to 'failed'.
    """
    if checkpoint_repo is None or not hasattr(cycle_repo, "list_running"):
        return []
    items: list[dict] = []
    for cycle in await cycle_repo.list_running():
        try:
            last_ok = await checkpoint_repo.last_ok(str(cycle.id))
        except Exception:  # noqa: BLE001 — a broken checkpoint is not fatal
            log.exception("Reading checkpoints for %s failed", cycle.id)
            continue
        items.append({
            "cycle_id": str(cycle.id),
            "repo": cycle.project_id,
            "triggered_by": cycle.triggered_by,
            "resume_from": last_ok.next_phase if last_ok else None,
        })
    return items
