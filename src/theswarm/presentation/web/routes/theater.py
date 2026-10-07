"""The cycle — the theater on V3 (M4, docs/plans/2026-10-v3-one-product.md).

`/cycles/{id}` draws a cycle: the phase stepper from the phases it
announced (its row's phases after a restart), the four agents, what
happened, the feature piece by piece, its pull requests — and it ends on
the demo. The page polls `/cycles/{id}/stage` while the cycle runs. The
V2 address `/c/{id}` redirects here (routes/customers.py). The data is
V2's `_stage_context`, kept in routes/v2.py until M6 moves it.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from theswarm.presentation.web.routes import stage

log = logging.getLogger(__name__)
router = APIRouter()

# What a phase reads as on the stepper, in the order work travels.
STEP_LABELS = {
    "prepare": "Prepare",
    "po_morning": "Plan",
    "techlead_breakdown": "Breakdown",
    "dev_loop": "",  # the loop itself, not a step
    "dev_iter": "Dev",
    "techlead_review": "Review",
    "dev_loop_end": "",
    "qa": "QA",
    "po_evening": "Report",
    "merge_held": "Merge",
    "finish": "",
    "cycle_log": "",
}
CANONICAL = ("prepare", "po_morning", "techlead_breakdown", "dev_iter", "techlead_review", "qa", "po_evening")
STATUS_CHIPS = {
    "running": ("Running", "running"),
    "queued": ("Queued", "waiting"),
    "pending": ("Queued", "waiting"),
    "completed": ("Completed", "verified"),
    "failed": ("Failed", "broken"),
    "cancelled": ("Cancelled", "waiting"),
}
_PR_RE = re.compile(r"#(\d+)")


# ── Where a cycle lives ──────────────────────────────────────────────


async def theater_target(state, cycle_id: str) -> str | None:
    """The cycle to draw for `cycle_id`: its continuation after a restart,
    itself when it is known (live or on its row), None when nothing is."""
    if stage._tracker_record(cycle_id) is not None:
        return cycle_id
    cycle = await state.get_cycle_status_query.execute(cycle_id)
    resumed_as = getattr(cycle, "resumed_as", "") if cycle is not None else ""
    if resumed_as and (
        stage._tracker_record(resumed_as) is not None
        or await stage._archived_record(state, resumed_as) is not None
    ):
        return resumed_as
    return cycle_id if cycle is not None else None


def _orphan_record(cycle):
    """A row still running that nothing runs (a restart took it): drawn
    from what the database knows, and said so — V1's archive used to."""
    from theswarm.api import CycleRecord, CycleStatus as TrackerStatus

    def iso(moment) -> str:
        return moment.isoformat() if moment else ""

    return CycleRecord(
        id=str(cycle.id), repo=cycle.project_id, description="", callback_url="",
        issue_number=cycle.issue_number, status=TrackerStatus(cycle.status.value),
        created_at=iso(cycle.started_at), started_at=iso(cycle.started_at),
        completed_at=iso(cycle.completed_at), error=cycle.error or None,
        trace_id=cycle.trace_id,
    )


async def _record_for(state, cycle_id: str):
    """(record, orphan): the live record, the finished row, or a row nothing
    runs any more; (None, False) when the cycle does not exist."""
    record = stage._tracker_record(cycle_id)
    if record is not None:
        return record, False
    record = await stage._archived_record(state, cycle_id)
    if record is not None:
        return record, False
    cycle_repo = getattr(state, "cycle_repo", None)
    if cycle_repo is None:
        return None, False
    try:
        from theswarm.domain.cycles.value_objects import CycleId

        cycle = await cycle_repo.get(CycleId(cycle_id))
    except Exception:  # noqa: BLE001
        log.exception("theater: reading cycle %s failed", cycle_id)
        return None, False
    if cycle is None:
        return None, False
    return _orphan_record(cycle), True


# ── The stepper, the pull requests, the header ───────────────────────


LABEL_MAX = 14


def _label(phase: str, dev_iterations: int) -> str:
    """A step's word: the known phases by name, Dev with its iteration; a
    row's free-text phase ("Checking branch protection…") cut short."""
    if phase == "dev_iter":
        return f"Dev · {dev_iterations}"
    if phase in STEP_LABELS:
        return STEP_LABELS[phase]
    text = phase.replace("_", " ").strip()
    text = text[:1].upper() + text[1:]
    return text if len(text) <= LABEL_MAX else text[:LABEL_MAX - 1].rstrip() + "…"


def _mmss(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return ""
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes}:{secs:02d}"


def steps_from_history(history: list[dict], status: str, now: float | None = None) -> list[dict]:
    """The stepper from the phases a cycle announced ({phase, ts}, oldest
    first): each announced phase with how long it took (the last one still
    counting while the cycle runs), then what is still to come."""
    now = now if now is not None else time.time()
    seen = [h for h in history if STEP_LABELS.get(h.get("phase", ""), "x") != ""]
    steps: list[dict] = []
    dev_iterations = 0
    for i, entry in enumerate(seen):
        phase = entry["phase"]
        if phase == "dev_iter":
            dev_iterations += 1
        started = float(entry.get("ts") or 0)
        ended = float(entry["end"]) if entry.get("end") else None  # a row's phase knows when it ended
        if ended is None and i + 1 < len(seen):
            ended = float(seen[i + 1].get("ts") or 0)
        last = i + 1 == len(seen)
        if last and status in ("running", "queued"):
            state, duration = "live", _mmss(now - started if started else None) + " …"
        elif last and status in ("failed", "cancelled"):
            state, duration = "failed", _mmss((ended or now) - started if started else None)
        else:
            state, duration = "done", _mmss((ended or now) - started if started else None)
        steps.append({"key": phase, "label": _label(phase, dev_iterations), "state": state, "time": duration})
    if status in ("running", "queued"):
        last_phase = seen[-1]["phase"] if seen else ""
        index = CANONICAL.index(last_phase) + 1 if last_phase in CANONICAL else 0
        for phase in CANONICAL[index:]:
            steps.append({"key": phase, "label": _label(phase, dev_iterations + 1) if phase == "dev_iter" else _label(phase, 0),
                          "state": "todo", "time": ""})
    return steps


def steps_from_row(cycle) -> list[dict]:
    """The stepper after a restart, from the row's phases (no live history)."""
    history = []
    for p in getattr(cycle, "phases", ()) or ():
        started = p.started_at.timestamp() if p.started_at else 0
        ended = p.completed_at.timestamp() if getattr(p, "completed_at", None) else None
        history.append({"phase": p.phase, "ts": started, "end": ended})
    status = getattr(cycle.status, "value", str(cycle.status))
    end = cycle.completed_at.timestamp() if getattr(cycle, "completed_at", None) else time.time()
    return steps_from_history(history, status, now=end)


def prs_from_feed(feed: list[dict], repo: str) -> list[dict]:
    """The pull requests the feed named, by number, the latest word on each."""
    found: dict[int, dict] = {}
    for entry in feed:
        kind = str(entry.get("kind", ""))
        text = str(entry.get("text", ""))
        if kind not in ("pr_opened", "review", "merged", "pr_merged") and "PR #" not in text and "pull request" not in text.lower():
            continue
        for number in _PR_RE.findall(text):
            n = int(number)
            found[n] = {"number": n, "text": text[:140], "kind": kind,
                        "href": f"https://github.com/{repo}/pull/{n}"}
    return [found[n] for n in sorted(found)]


def _clock(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone(timezone.utc).strftime("%H:%M UTC")
    except (TypeError, ValueError):
        return ""


def _elapsed(record) -> str:
    try:
        start = datetime.fromisoformat(record.started_at or record.created_at)
        end = datetime.fromisoformat(record.completed_at) if record.completed_at else datetime.now(timezone.utc)
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        minutes = int((end - start).total_seconds() // 60)
        return f"{minutes // 60} h {minutes % 60:02d} min" if minutes >= 60 else f"{minutes} min"
    except (TypeError, ValueError):
        return ""


async def _project_of(state, repo: str) -> dict:
    """Where the cycle's repository lives on V3: its customer and project page."""
    base = state.base_path
    try:
        project = next((p for p in await state.project_repo.list_all() if str(p.repo) == repo), None)
    except Exception:  # noqa: BLE001
        project = None
    customer = None
    customer_repo = getattr(state, "customer_repo", None)
    if project is not None and customer_repo is not None:
        try:
            customer = await customer_repo.get(project.customer_id)
        except Exception:  # noqa: BLE001
            customer = None
    slug = customer.slug if customer is not None else "internal"
    name = project.repo.name if project is not None else repo.partition("/")[2]
    return {
        "customer_name": customer.name if customer is not None else "Internal",
        "customer_href": f"{base}/c/{slug}",
        "name": name,
        "href": f"{base}/c/{slug}/p/{name}" if project is not None else f"{base}/r/{repo}",
        "feature_href": f"{base}/c/{slug}/p/{name}/f/" if project is not None else "",
    }


async def theater_context(request: Request, record, orphan: bool = False) -> dict:
    """V2's stage context, plus what the V3 theater draws on top."""
    from theswarm.application.services.progress_bridge import get_phase_history

    state = request.app.state
    context = await stage._stage_context(request, record)
    status = record.status.value
    history = get_phase_history(record.id)
    steps = steps_from_history(history, status) if history else []
    spent = ""
    cycle_repo = getattr(state, "cycle_repo", None)
    if cycle_repo is not None:
        try:
            from theswarm.domain.cycles.value_objects import CycleId

            cycle = await cycle_repo.get(CycleId(record.id))
            if cycle is not None:
                if not steps:
                    steps = steps_from_row(cycle)
                if cycle.total_cost_usd:
                    spent = f"${cycle.total_cost_usd:.2f}"
        except Exception:  # noqa: BLE001 — the page stays
            log.exception("theater: reading the row of %s failed", record.id)
    result = getattr(record, "result", None) or {}
    if not spent and isinstance(result, dict) and result.get("cost_usd"):
        spent = f"${float(result['cost_usd']):.2f}"
    label, kind = STATUS_CHIPS.get(status, (status.capitalize(), "waiting"))
    resumable_from = None
    checkpoints = getattr(state, "checkpoint_repo", None)
    if status == "failed" and checkpoints is not None:
        try:
            last_ok = await checkpoints.last_ok(record.id)
            resumable_from = last_ok.next_phase if last_ok else None
        except Exception:  # noqa: BLE001
            log.exception("theater: reading the checkpoints of %s failed", record.id)
    context.update({
        "resumable_from": resumable_from,
        "steps": steps,
        "prs": prs_from_feed(context.get("feed", []), record.repo),
        "status_label": label,
        "status_kind": kind,
        "started": _clock(record.started_at or record.created_at),
        "elapsed": _elapsed(record),
        "spent": spent,
        "dev_iterations": sum(1 for h in history if h.get("phase") == "dev_iter"),
        "orphan": orphan,
        "project": await _project_of(state, record.repo),
        "cancel_url": f"{state.base_path}/api/cycle/{record.id}/cancel",
        "stage_url": f"{state.base_path}/cycles/{record.id}/stage",
    })
    return context


# ── The routes ───────────────────────────────────────────────────────


@router.post("/cycles/{cycle_id}/resume")
async def resume(request: Request, cycle_id: str) -> RedirectResponse:
    """Resume a failed cycle from the phase after its last good checkpoint
    (Sprint G5), on V3 since M5: the theater's button posts here, and the
    continuation opens in the theater. V1's route of the same address goes
    with V1 at M6."""
    from theswarm.api import CycleRequest, get_cycle_tracker, run_api_cycle

    state = request.app.state
    base = state.base_path
    checkpoint_repo = getattr(state, "checkpoint_repo", None)
    if checkpoint_repo is None:
        return RedirectResponse(f"{base}/cycles/{cycle_id}", status_code=303)
    last_ok = await checkpoint_repo.last_ok(cycle_id)
    resume_from = last_ok.next_phase if last_ok else None
    if resume_from is None:  # nothing to resume from: back to the theater, nothing done
        return RedirectResponse(f"{base}/cycles/{cycle_id}", status_code=303)

    original = await state.get_cycle_status_query.execute(cycle_id)
    repo = original.project_id if original is not None else ""
    tracker = get_cycle_tracker()
    req = CycleRequest(repo=repo, description=f"Resume of {cycle_id} from {resume_from}")
    record = tracker.create(req)
    task = asyncio.create_task(run_api_cycle(
        record.id, repo, req.description, "", getattr(state, "allowed_repos", []),
        event_bus=getattr(state, "event_bus", None), report_repo=getattr(state, "report_repo", None),
        base_path=base, project_repo=getattr(state, "project_repo", None),
        cycle_repo=getattr(state, "cycle_repo", None), project_id=repo,
        checkpoint_repo=checkpoint_repo, resume_from=resume_from,
        role_assignment_service=getattr(state, "role_assignment_service", None),
    ))
    tracker.set_task(record.id, task)
    log.info("Cycle %s resumed as %s from phase %s", cycle_id, record.id, resume_from)
    return RedirectResponse(f"{base}/cycles/{record.id}", status_code=303)


@router.get("/cycles/{cycle_id}", response_class=HTMLResponse)
async def theater(request: Request, cycle_id: str):
    state = request.app.state
    target = await theater_target(state, cycle_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    if target != cycle_id:
        # A restart interrupted it and the resumer continued it: the theater
        # of the continuation is where this cycle now lives.
        return RedirectResponse(f"{state.base_path}/cycles/{target}", status_code=303)
    record, orphan = await _record_for(state, cycle_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return state.templates.TemplateResponse("theater.html", await theater_context(request, record, orphan))


@router.get("/cycles/{cycle_id}/stage", response_class=HTMLResponse)
async def theater_stage(request: Request, cycle_id: str):
    record, orphan = await _record_for(request.app.state, cycle_id)
    if record is None:
        raise HTTPException(status_code=404, detail="")
    return request.app.state.templates.TemplateResponse(
        "_stage.html", await theater_context(request, record, orphan),
    )
