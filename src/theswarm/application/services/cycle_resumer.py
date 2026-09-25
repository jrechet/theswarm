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

# What an interrupted cycle's row says once the boot reap has failed it; a
# cycle that is not continued gets the reason after it.
RESTART_REASON = "Interrupted by a restart (a deploy or a crash)"


@dataclass(frozen=True)
class ResumePlan:
    """One interrupted cycle worth continuing."""

    cycle_id: str
    repo: str
    resume_from: str
    depth: int
    issue_number: int | None = None  # the pinned issue the cycle was built for

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
            issue_number=item.get("issue_number"),
        ))
        if len(plans) >= max_per_boot:
            break
    return plans


async def collect_interrupted(cycle_repo, checkpoint_repo, graph_checkpointer=None) -> list[dict]:
    """Read cycles left 'running' by a dead process, with their checkpoints.

    Must run *before* the orphan reap, which flips those rows to 'failed'.

    Since V2 M4 the resume itself continues the cycle's LangGraph thread;
    when a ``graph_checkpointer`` is given, a cycle with no thread on it
    (one older than M4, or run on a memory saver) gets no ``resume_from``
    and is left to the reaper — never a resume that cannot start.
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
        resume_from = last_ok.next_phase if last_ok else None
        issue_number = None
        not_resumable = ""
        thread = None
        if graph_checkpointer is not None:
            # A continuation runs on the thread of the cycle it continues.
            thread_id = await _thread_id_of(cycle_repo, str(cycle.id))
            thread = await _graph_thread(graph_checkpointer, thread_id)
        if resume_from and graph_checkpointer is not None:
            if thread is None:
                log.info("Cycle %s has no graph checkpoint — not resumed", cycle.id)
                resume_from = None
                not_resumable = NO_GRAPH_THREAD
            else:
                issue_number = _target_issue_of(thread)
        items.append({
            "cycle_id": str(cycle.id),
            "repo": cycle.project_id,
            "triggered_by": cycle.triggered_by,
            "resume_from": resume_from,
            "issue_number": issue_number,
            "not_resumable": not_resumable,
            # What the chain had spent at its last checkpoint: written on the
            # row if nobody continues it (a continuation inherits it).
            "cost_usd": _total_cost_of(thread),
        })
    return items


NO_GRAPH_THREAD = "no graph checkpoint (it predates the durable cycle)"


def _total_cost_of(thread) -> float:
    checkpoint = getattr(thread, "checkpoint", None) or {}
    value = (checkpoint.get("channel_values") or {}).get("total_cost")
    return float(value) if isinstance(value, (int, float)) else 0.0


async def spent_so_far(graph_checkpointer, thread_id: str) -> float:
    """The cycle's running total at its last graph checkpoint, 0.0 when unknown.

    A failed cycle's row said $0 while its checkpoint knew better (csv-export,
    2026-09-25: scored $0.00 after two phases and three merged PRs).
    """
    if graph_checkpointer is None or not thread_id:
        return 0.0
    return _total_cost_of(await _graph_thread(graph_checkpointer, thread_id))


async def _thread_id_of(cycle_repo, cycle_id: str) -> str:
    """The graph thread a cycle runs on: its resume chain's first cycle."""
    origin_of = getattr(cycle_repo, "origin_of", None)
    if origin_of is None:
        return cycle_id
    try:
        return await origin_of(cycle_id)
    except Exception:  # noqa: BLE001 — fall back to the cycle's own id
        log.exception("Finding the origin of cycle %s failed", cycle_id)
        return cycle_id


def _why_not_resumed(item: dict, max_depth: int) -> str:
    # The cap first: whatever else is true of a continuation, the cap is why
    # it stays down (46ff31375dce had finished its dev loop, and still no
    # phase was on record under its id).
    if resume_depth(item.get("triggered_by") or "") >= max_depth:
        return ("it was already an automatic resume, and a second interruption "
                "needs a person to look")
    if item.get("not_resumable"):
        return str(item["not_resumable"])
    if not item.get("resume_from"):
        return "no phase had finished yet, there was nothing to continue"
    if not (item.get("repo") or "").strip():
        return "its repository is unknown"
    return f"more than {MAX_RESUMES_PER_BOOT} cycles were interrupted at once"


def not_resumed_reasons(
    interrupted: list[dict],
    plans: list[ResumePlan],
    *,
    max_depth: int = MAX_RESUME_DEPTH,
) -> dict[str, str]:
    """Why each interrupted cycle that is not continued was left, by id.

    A continued one needs no reason: its row points at the continuation.
    """
    planned = {plan.cycle_id for plan in plans}
    return {
        item["cycle_id"]: f"{RESTART_REASON}; not resumed — {_why_not_resumed(item, max_depth)}"
        for item in interrupted
        if item.get("cycle_id") and item["cycle_id"] not in planned
    }


async def record_not_resumed(cycle_repo, interrupted: list[dict], plans: list[ResumePlan]) -> None:
    """Write each left-behind cycle's reason on its row (after the reap)."""
    spent = {item.get("cycle_id"): float(item.get("cost_usd") or 0.0) for item in interrupted}
    for cycle_id, reason in not_resumed_reasons(interrupted, plans).items():
        log.info("Cycle %s: %s", cycle_id, reason)
        try:
            await cycle_repo.set_error(cycle_id, reason)
            if spent.get(cycle_id) and hasattr(cycle_repo, "set_spend"):
                await cycle_repo.set_spend(cycle_id, spent[cycle_id])
        except Exception:  # noqa: BLE001 — a reason is not worth a failed boot
            log.exception("Recording why cycle %s was not resumed failed", cycle_id)


async def _graph_thread(graph_checkpointer, cycle_id: str):
    """The cycle's latest graph checkpoint tuple, None when it has none."""
    try:
        return await graph_checkpointer.aget_tuple({"configurable": {"thread_id": cycle_id}})
    except Exception:  # noqa: BLE001 — an unreadable thread is a missing one
        log.exception("Reading the graph checkpoint for %s failed", cycle_id)
        return None


async def _has_graph_thread(graph_checkpointer, cycle_id: str) -> bool:
    return await _graph_thread(graph_checkpointer, cycle_id) is not None


def _target_issue_of(thread) -> int | None:
    """The pinned issue the checkpointed cycle was running for, if any."""
    checkpoint = getattr(thread, "checkpoint", None) or {}
    value = (checkpoint.get("channel_values") or {}).get("target_issue")
    return int(value) if isinstance(value, int) else None
