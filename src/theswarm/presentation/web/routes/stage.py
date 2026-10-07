"""The theater's data (M6, from the V2 module): the four stations, the flow
graph from the phases the cycle announced, the stage context the theater
polls, a finished cycle drawn from its row, the trace link."""

from __future__ import annotations

import logging
import os
import re

from fastapi import Request

from theswarm.application.services.progress_bridge import PHASE_OWNER
from theswarm.presentation.web.routes.common import _demo_card

log = logging.getLogger(__name__)


_STATIONS = (
    ("po", "PO", "Product Owner"),
    ("techlead", "TL", "Tech Lead"),
    ("dev", "DEV", "Developer"),
    ("qa", "QA", "QA"),
)


_ROLE_ALIASES = {
    "po": "po", "product_owner": "po", "productowner": "po",
    "techlead": "techlead", "tech_lead": "techlead", "tl": "techlead",
    "dev": "dev", "developer": "dev",
    "qa": "qa", "tester": "qa",
}


_FEED_LIMIT = 250


def _normalize_role(raw: str) -> str | None:
    return _ROLE_ALIASES.get(raw.strip().lower().replace("-", "_"))


def _stations(record, progress: list[dict]) -> list[dict]:
    """Map live progress onto the four fixed stations.

    ``progress`` is most-recent-first; the freshest role is the active
    station, everything before it on the rail is done, everything after
    waits. On failure the active station carries the cross.
    """
    latest: dict[str, str] = {}
    active: str | None = None
    for row in progress:
        role = _normalize_role(str(row.get("role", "")))
        if role is None:
            continue
        if role not in latest:
            latest[role] = str(row.get("message", ""))
        if active is None:
            active = role

    keys = [key for key, _, _ in _STATIONS]
    status = record.status.value
    if active is None:
        active_index = 0 if status == "running" else -1
    else:
        active_index = keys.index(active)

    stations: list[dict] = []
    for index, (key, glyph, name) in enumerate(_STATIONS):
        if status == "completed":
            state = "done"
        elif status in ("failed", "cancelled"):
            if active_index == -1 or index > active_index:
                state = "waiting"
            elif index == active_index:
                state = "failed"
            else:
                state = "done"
        elif status in ("running", "queued") and active_index >= 0:
            if index < active_index:
                state = "done"
            elif index == active_index:
                state = "active"
            else:
                state = "waiting"
        else:
            state = "waiting"
        stations.append({
            "key": key, "glyph": glyph, "name": name,
            "state": state, "message": latest.get(key, ""),
        })
    return stations


_PHASE_LABEL = {
    "po_morning": "planning",
    "techlead_breakdown": "breaking down",
    "dev_loop": "building",
    "dev_iter": "building",
    "techlead_review": "reviewing",
    "qa": "testing & demo",
    "po_evening": "reporting",
}


_EDGES = (
    ("po", "techlead", "stories"),
    ("techlead", "dev", "tasks"),
    ("dev", "techlead", "review"),
    ("techlead", "qa", "merged"),
    ("qa", "po", "report"),
)


def _edge_counts(pinned) -> dict[tuple[str, str], int | None]:
    """What the pinned issue can tell about the edges: how many tasks the
    TechLead handed the Dev, how many came back for review."""
    children = getattr(pinned, "children", None) or []
    done = getattr(pinned, "done", 0) or 0
    return {
        ("techlead", "dev"): len(children) or None,
        ("dev", "techlead"): done or None,
    }


def _graph(record, phases: list[dict], progress: list[dict], pinned=None) -> dict:
    """Nodes and edges of the flow, from the phases the cycle announced.

    The rail used to guess: whoever spoke last was "active", everyone
    before them "done". Wrong as soon as the TechLead comes back to review
    or the Dev iterates. With the phase history the owner of the current
    phase is active, whoever owned an earlier phase is done, and an edge
    is in flight exactly when its source is done and its target active.

    A cycle that never announced a phase — the CLI, or one older than the
    channel — keeps the guess, so nothing goes dark.
    """
    stations = _stations(record, progress)
    by_key = {node["key"]: node for node in stations}
    status = record.status.value
    seen = [p["phase"] for p in phases if p.get("phase") in PHASE_OWNER]
    for node in stations:
        node["phase"] = ""
    if seen:
        current = seen[-1]
        owner_now = PHASE_OWNER[current]
        ran = {PHASE_OWNER[p] for p in seen}
        for key, node in by_key.items():
            if status == "completed":
                state = "done" if key in ran else "waiting"
            elif status in ("failed", "cancelled"):
                if key == owner_now:
                    state = "failed"
                else:
                    state = "done" if key in ran else "waiting"
            else:
                if key == owner_now:
                    state = "active"
                else:
                    state = "done" if key in ran else "waiting"
            node["state"] = state
            if key == owner_now and state == "active":
                node["phase"] = _PHASE_LABEL.get(current, current)

    counts = _edge_counts(pinned)
    edges: dict[str, dict] = {}
    for src, dst, label in _EDGES:
        s_state, d_state = by_key[src]["state"], by_key[dst]["state"]
        if d_state == "active" and s_state == "done":
            flow = "flowing"
        elif s_state == "done" and d_state in ("done", "failed"):
            flow = "done"
        else:
            flow = "idle"
        edges[f"{src}-{dst}"] = {
            "from": src, "to": dst, "label": label, "flow": flow,
            "count": counts.get((src, dst)),
        }
    return {"nodes": stations, "edge": edges}


async def _stage_context(request: Request, record) -> dict:
    from theswarm.application.services.pinned_issue import load_pinned_issue
    from theswarm.application.services.progress_bridge import (
        get_live_progress,
        get_phase_history,
        is_telling,
    )

    progress = get_live_progress(record.id)
    phases = get_phase_history(record.id)

    feed: list[dict] = []
    thoughts_query = getattr(request.app.state, "get_agent_thoughts_query", None)
    if thoughts_query is not None:
        try:
            entries = await thoughts_query.execute(record.id, include_activity=True)
        except Exception:  # noqa: BLE001 — the feed degrades, the page stays
            log.exception("V2: reading thoughts for %s failed", record.id)
            entries = []
        glyphs = {key: glyph for key, glyph, _ in _STATIONS}
        entries = [e for e in entries if e.kind == "step" or is_telling(e.text)]
        for entry in reversed(entries[-_FEED_LIMIT:]):
            role = _normalize_role(entry.agent) or ""
            feed.append({
                "time": entry.occurred_at.strftime("%H:%M:%S"),
                "agent": role or entry.agent,
                "glyph": glyphs.get(role, entry.agent[:3].upper()),
                "kind": entry.kind,
                "text": entry.text,
            })

    pinned = await load_pinned_issue(record.repo, record.issue_number)
    graph = _graph(record, phases, progress, pinned)
    demo = await _cycle_demo(request.app.state, record.id)
    return {
        "record": record,
        "demo": demo,
        # The report is saved just after the cycle is marked completed: the
        # page keeps polling until it is there (theater.html).
        "demo_pending": demo is None and record.status.value == "completed",
        "stations": graph["nodes"],
        "graph": graph,
        "pinned": pinned,
        "feed": feed,
        "trace_url": trace_url(getattr(record, "trace_id", "")),
        "resumed_from": resumed_from(getattr(record, "description", "")),
    }


async def _cycle_demo(state, cycle_id: str) -> dict | None:
    """The demo of this cycle, once its report is stored; None before, or
    when the store is missing or unwell (the stage stays)."""
    report_repo = getattr(state, "report_repo", None)
    if report_repo is None:
        return None
    try:
        reports = await report_repo.list_by_cycle(cycle_id, limit=1)
    except Exception:  # noqa: BLE001 — the stage degrades, the page stays
        log.exception("V2: reading the demo of cycle %s failed", cycle_id)
        return None
    return _demo_card(state, reports[0]) if reports else None


_RESUME_OF_RE = re.compile(r"^Resume of ([0-9a-f]{12}) from ")


def resumed_from(description: str) -> str:
    """The cycle a continuation resumes (its description, set by the boot
    resumer: "Resume of <id> from <phase>"), "" for any other cycle. Since
    a continuation shows its pinned issue as its title (#214), this is the
    only place left that says where its first phases ran."""
    match = _RESUME_OF_RE.match(description or "")
    return match.group(1) if match else ""


def trace_url(trace_id: str, seq_url: str | None = None) -> str:
    """Where to read this cycle's trace in Seq — "" without a tracer or Seq."""
    from urllib.parse import quote

    if seq_url is None:
        seq_url = os.getenv("SEQ_URL", "")
    if not trace_id or not seq_url:
        return ""
    return f"{seq_url.rstrip('/')}/#/events?filter={quote(f"@tr = '{trace_id}'", safe='')}"


def _tracker_record(cycle_id: str):
    from theswarm.api import get_cycle_tracker

    return get_cycle_tracker().get(cycle_id)


_FINISHED = frozenset({"completed", "failed", "cancelled"})


async def _archived_record(state, cycle_id: str):
    """A finished cycle the tracker no longer knows, drawn from its row.

    The tracker is in-memory: after any restart — every deploy — a
    finished cycle's link fell back to the V1 archive and its demo card
    was gone. Its stations are done, its feed is in the event store, its
    demo in the report store, its issue on the row (v032). A row still
    "running" that the tracker does not know is nobody's cycle any more:
    None, and the archive view says what the database knows.
    """
    from theswarm.api import CycleRecord, CycleStatus as TrackerStatus
    from theswarm.domain.cycles.value_objects import CycleId

    cycle_repo = getattr(state, "cycle_repo", None)
    if cycle_repo is None:
        return None
    try:
        cycle = await cycle_repo.get(CycleId(cycle_id))
    except Exception:  # noqa: BLE001 — the archive view stays the way out
        log.exception("V2: reading cycle %s failed", cycle_id)
        return None
    if cycle is None or cycle.status.value not in _FINISHED:
        return None

    def iso(moment) -> str:
        return moment.isoformat() if moment else ""

    return CycleRecord(
        id=str(cycle.id), repo=cycle.project_id, description="", callback_url="",
        issue_number=cycle.issue_number, status=TrackerStatus(cycle.status.value),
        created_at=iso(cycle.started_at), started_at=iso(cycle.started_at),
        completed_at=iso(cycle.completed_at), error=cycle.error or None,
        trace_id=cycle.trace_id,
    )
