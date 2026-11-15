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
    "fix_intake": "Intake",  # the fix flow: the issue is the task
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
    "paused": ("Paused", "waiting"),
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


def _waits(record) -> str:
    """What a queued cycle waits for (`shell.waiting_words`); never fails the page."""
    from theswarm.presentation.web.shell import waiting_words

    try:
        return waiting_words(record)
    except Exception:  # noqa: BLE001
        log.exception("theater: reading the queue failed")
        return ""


def _finished_at(record) -> float | None:
    """When a finished cycle finished — its last phase stops counting there.
    Without it the report phase of a cycle done at 07:54 read 546 minutes
    at 17:00 (prod, e73bf089784a, 2026-10-11)."""
    try:
        if not record.completed_at:
            return None
        end = datetime.fromisoformat(record.completed_at)
        return (end if end.tzinfo else end.replace(tzinfo=timezone.utc)).timestamp()
    except (AttributeError, TypeError, ValueError):
        return None


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


def _pause_asked(cycle_id: str) -> bool:
    from theswarm.api import get_cycle_tracker

    return get_cycle_tracker().pause_requested(cycle_id)


async def _continued(state, cycle_id: str) -> bool:
    """A cycle another one already continues (a deploy's resume, or a person's): no second resume."""
    try:
        row = await state.get_cycle_status_query.execute(cycle_id)
    except Exception:  # noqa: BLE001 — the page stays
        log.exception("theater: reading the row of %s failed", cycle_id)
        return False
    return bool(getattr(row, "resumed_as", "")) if row is not None else False


async def theater_context(request: Request, record, orphan: bool = False) -> dict:
    """V2's stage context, plus what the V3 theater draws on top."""
    from theswarm.application.services.progress_bridge import get_phase_history

    state = request.app.state
    context = await stage._stage_context(request, record)
    status = record.status.value
    history = get_phase_history(record.id)
    steps = steps_from_history(history, status, now=_finished_at(record)) if history else []
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
    if status in ("running", "queued") and getattr(record, "spent_usd", 0):
        spent = f"${record.spent_usd:.2f} so far"  # A2: live, call by call
    label, kind = STATUS_CHIPS.get(status, (status.capitalize(), "waiting"))
    resumable_from = None
    checkpoints = getattr(state, "checkpoint_repo", None)
    continued = await _continued(state, record.id) if status in ("failed", "paused") else False
    if status == "failed" and checkpoints is not None and not continued:
        try:
            last_ok = await checkpoints.last_ok(record.id)
            resumable_from = last_ok.next_phase if last_ok else None
        except Exception:  # noqa: BLE001
            log.exception("theater: reading the checkpoints of %s failed", record.id)
    context.update({
        "resumable_from": resumable_from,
        # A3.2: a pause asked for and not taken yet; a paused cycle nobody continued
        "pausing": status == "running" and _pause_asked(record.id),
        "paused_resumable": status == "paused" and checkpoints is not None and not continued,
        "steps": steps,
        "prs": prs_from_feed(context.get("feed", []), record.repo),
        "status_label": label,
        "waits": _waits(record),
        "status_kind": kind,
        "started": _clock(record.started_at or record.created_at),
        "elapsed": _elapsed(record),
        "spent": spent,
        "dev_iterations": sum(1 for h in history if h.get("phase") == "dev_iter"),
        "orphan": orphan,
        "project": await _project_of(state, record.repo),
        "cancel_url": f"{state.base_path}/api/cycle/{record.id}/cancel",
        # A3.1: the field to say something to the cycle, and what the last post answered
        "can_say": getattr(state, "cycle_inbox", None) is not None and record.status.value in ("running", "queued"),
        "said": request.query_params.get("said", ""),
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
    original = await state.get_cycle_status_query.execute(cycle_id)
    # A paused cycle (A3.2) goes on from its graph thread, whatever phase it
    # stopped before; a failed one needs a phase that finished.
    paused = original is not None and getattr(original, "status", "") == "paused"
    if resume_from is None and not paused:  # nothing to resume from: back to the theater, nothing done
        return RedirectResponse(f"{base}/cycles/{cycle_id}", status_code=303)

    if original is not None and original.resumed_as:  # already continued: a second click opens it
        return RedirectResponse(f"{base}/cycles/{original.resumed_as}", status_code=303)
    repo = original.project_id if original is not None else ""
    issue_number = original.issue_number if original is not None else None
    cycle_repo = getattr(state, "cycle_repo", None)
    # The durable graph runs on the thread of its resume chain's first cycle:
    # the button passed none, the continuation looked for a checkpoint under its
    # own new id and died on CycleNotResumable (the review of 2026-11-11).
    from theswarm.application.services.cycle_resumer import _thread_id_of

    thread = await _thread_id_of(cycle_repo, cycle_id) if cycle_repo is not None else cycle_id
    tracker = get_cycle_tracker()
    req = CycleRequest(repo=repo, description=f"Resume of {cycle_id} from {resume_from or 'its pause'}",
                       issue_number=issue_number)
    record = tracker.create(req)
    task = asyncio.create_task(run_api_cycle(
        record.id, repo, req.description, "", getattr(state, "allowed_repos", []),
        event_bus=getattr(state, "event_bus", None), report_repo=getattr(state, "report_repo", None),
        base_path=base, project_repo=getattr(state, "project_repo", None),
        cycle_repo=cycle_repo, project_id=repo,
        checkpoint_repo=checkpoint_repo, resume_from=resume_from,
        resume_cycle_id=thread, issue_number=issue_number,
        # A person's resume, not the boot's: it does not count toward the one
        # automatic resume a deploy may make (`cycle_resumer.MAX_RESUME_DEPTH`).
        triggered_by=MANUAL_RESUME_TRIGGER,
        role_assignment_service=getattr(state, "role_assignment_service", None),
    ))
    tracker.set_task(record.id, task)
    if cycle_repo is not None:
        try:
            await cycle_repo.mark_resumed(cycle_id, record.id)
        except Exception:  # noqa: BLE001 — the continuation runs; only the link is missing
            log.exception("Linking cycle %s to its resume %s failed", cycle_id, record.id)
    log.info("Cycle %s resumed as %s from phase %s (thread %s)", cycle_id, record.id, resume_from, thread)
    return RedirectResponse(f"{base}/cycles/{record.id}", status_code=303)


MANUAL_RESUME_TRIGGER = "resume"


@router.post("/cycles/{cycle_id}/pause")
async def pause(request: Request, cycle_id: str):
    """A3.2: stop this cycle at the end of the phase it is in. The phase
    finishes and is kept; the cycle's place goes to whoever waits; Resume
    goes on from the next phase."""
    from theswarm.api import get_cycle_tracker
    from theswarm.presentation.web.routes.customers import _refused, current_actor

    state = request.app.state
    actor = await current_actor(request)
    if actor is None or not actor.is_owner:
        return _refused(request, actor)
    asked = get_cycle_tracker().pause(cycle_id)
    if asked:
        log.info("Cycle %s: pause asked by %s", cycle_id, getattr(actor, "login", "") or "owner")
    return RedirectResponse(f"{state.base_path}/cycles/{cycle_id}", status_code=303)


@router.post("/cycles/{cycle_id}/messages")
async def say_to_cycle(request: Request, cycle_id: str):
    """A3.1: the owner's word to a running cycle. It waits in the cycle's
    inbox and reaches the working agent at its next tool call, or at the
    head of the next Claude call; the feed shows it, and when it was read."""
    from theswarm.application.services.cycle_inbox import InboxError
    from theswarm.presentation.web.routes.customers import _refused, current_actor

    state = request.app.state
    actor = await current_actor(request)
    if actor is None or not actor.is_owner:
        return _refused(request, actor)
    target = await theater_target(state, cycle_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    record, _ = await _record_for(state, target)
    back = f"{state.base_path}/cycles/{target}"
    inbox = getattr(state, "cycle_inbox", None)
    if record is None or inbox is None or record.status.value not in ("running", "queued"):
        return RedirectResponse(f"{back}?said=over", status_code=303)
    form = await request.form()
    try:
        # "Stop and say" (A3.3) cuts the call that is running; "Send" waits for its next step.
        await inbox.post(target, str(form.get("message") or ""), urgent=form.get("how") == "stop",
                         author=getattr(actor, "login", "") or "owner", project_id=record.repo)
    except InboxError:
        return RedirectResponse(f"{back}?said=empty", status_code=303)
    return RedirectResponse(f"{back}?said=1", status_code=303)


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
