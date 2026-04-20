"""Headless cycle models — CycleTracker and CycleRequest/CycleRecord.

Route registration has moved to presentation/web/routes/api.py.
This module only contains the in-memory models used by cycle execution.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel

log = logging.getLogger(__name__)


class CycleStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CycleRequest(BaseModel):
    repo: str
    description: str = ""
    callback_url: str = ""


class CycleRecord(BaseModel):
    id: str
    repo: str
    description: str
    callback_url: str
    status: CycleStatus
    created_at: str
    started_at: str = ""
    completed_at: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None


class CycleTracker:
    """In-memory tracker for API-initiated cycles."""

    def __init__(self) -> None:
        self._cycles: dict[str, CycleRecord] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def create(self, req: CycleRequest) -> CycleRecord:
        cycle_id = uuid.uuid4().hex[:12]
        record = CycleRecord(
            id=cycle_id,
            repo=req.repo,
            description=req.description,
            callback_url=req.callback_url,
            status=CycleStatus.QUEUED,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._cycles[cycle_id] = record
        # Cap at 100 records
        if len(self._cycles) > 100:
            oldest = min(self._cycles.values(), key=lambda c: c.created_at)
            self._cycles.pop(oldest.id, None)
        return record

    def get(self, cycle_id: str) -> CycleRecord | None:
        return self._cycles.get(cycle_id)

    def list_recent(self, limit: int = 20) -> list[CycleRecord]:
        records = sorted(self._cycles.values(), key=lambda c: c.created_at, reverse=True)
        return records[:limit]

    def update_status(self, cycle_id: str, status: CycleStatus, **kwargs) -> None:
        record = self._cycles.get(cycle_id)
        if record:
            record.status = status
            for k, v in kwargs.items():
                if hasattr(record, k):
                    setattr(record, k, v)

    def set_task(self, cycle_id: str, task: asyncio.Task) -> None:
        self._tasks[cycle_id] = task

    def cancel(self, cycle_id: str) -> bool:
        task = self._tasks.get(cycle_id)
        if task and not task.done():
            task.cancel()
            self.update_status(cycle_id, CycleStatus.CANCELLED)
            return True
        return False


# Singleton
_tracker = CycleTracker()


def get_cycle_tracker() -> CycleTracker:
    return _tracker


async def _emit_demo_ready(
    *,
    event_bus: object,
    report_repo: object | None,
    base_path: str,
    cycle_id: str,
    repo: str,
    result: dict[str, Any],
) -> None:
    """Build a DemoReport from the cycle result and publish DemoReady.

    Tolerates a missing report_repo (logs a warning and still publishes the
    event so the UI toast fires, using a transient report id).
    """
    try:
        from theswarm.application.services.report_generator import ReportGenerator
        from theswarm.domain.cycles.entities import Cycle
        from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
        from theswarm.domain.reporting.events import DemoReady

        cycle = Cycle(
            id=CycleId(cycle_id),
            project_id=repo,
            status=CycleStatus.COMPLETED,
            total_cost_usd=result.get("cost_usd", 0.0),
            prs_opened=tuple(
                p.get("number", 0) if isinstance(p, dict) else int(p)
                for p in result.get("prs", [])
                if p is not None
            ),
            prs_merged=tuple(
                r.get("pr_number", 0)
                for r in result.get("reviews", [])
                if isinstance(r, dict) and r.get("decision") == "APPROVE"
            ),
        )

        thumb_rel_preview = ""
        demo_dict = result.get("demo_report") or {}
        if isinstance(demo_dict, dict):
            thumb_rel_preview = demo_dict.get("thumbnail_path", "") or ""

        report = ReportGenerator().generate(cycle, thumbnail_rel_path=thumb_rel_preview)

        if report_repo is not None:
            try:
                await report_repo.save(report)
            except Exception:
                log.exception("Failed to save DemoReport for cycle %s", cycle_id)
        else:
            log.warning(
                "report_repo is None; publishing DemoReady without persistence (cycle=%s)",
                cycle_id,
            )

        prefix = base_path.rstrip("/")
        play_url = f"{prefix}/demos/{report.id}/play"
        title = f"{repo} — {datetime.now().strftime('%Y-%m-%d')}"

        # F4 — surface the generated JPEG thumbnail (or first screenshot) so
        # the SSE toast and Mattermost DM can show a preview image.
        thumb_rel = thumb_rel_preview or report.thumbnail_path or ""
        thumbnail_url = f"{prefix}/artifacts/{thumb_rel}" if thumb_rel else ""

        await event_bus.publish(DemoReady(
            cycle_id=CycleId(cycle_id),
            project_id=repo,
            report_id=report.id,
            play_url=play_url,
            title=title,
            thumbnail_url=thumbnail_url,
        ))
    except Exception:
        log.exception("Failed to emit DemoReady for cycle %s", cycle_id)


async def send_callback(url: str, payload: dict) -> None:
    """POST cycle result to a callback URL."""
    try:
        import urllib.request
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: urllib.request.urlopen(req, timeout=10))
        log.info("Callback sent to %s", url)
    except Exception:
        log.exception("Failed to send callback to %s", url)


async def run_api_cycle(
    cycle_id: str,
    repo: str,
    description: str,
    callback_url: str,
    allowed_repos: list[str],
    event_bus: object | None = None,
    report_repo: object | None = None,
    base_path: str = "",
    project_repo: object | None = None,
    cycle_repo: object | None = None,
    project_id: str = "",
) -> None:
    """Execute a cycle initiated via the API."""
    from theswarm.cycle import run_daily_cycle
    from theswarm.config import CycleConfig

    tracker = get_cycle_tracker()

    # Validate repo against allowlist
    if allowed_repos and repo not in allowed_repos:
        tracker.update_status(
            cycle_id, CycleStatus.FAILED,
            error=f"Repo '{repo}' not in allowed list: {allowed_repos}",
            completed_at=datetime.now().isoformat(timespec="seconds"),
        )
        return

    # Sprint B C4 — budget/pause gate.
    if project_repo is not None and cycle_repo is not None and project_id:
        try:
            from theswarm.application.services.budget_guard import (
                BudgetGuard,
                CycleBlocked as BudgetCycleBlocked,
            )
            project = await project_repo.get(project_id)
            if project is not None:
                guard = BudgetGuard(cycle_repo)
                try:
                    await guard.check(project)
                except BudgetCycleBlocked as e:
                    tracker.update_status(
                        cycle_id, CycleStatus.FAILED,
                        error=f"blocked: {e.reason}",
                        completed_at=datetime.now().isoformat(timespec="seconds"),
                    )
                    if event_bus is not None:
                        from theswarm.domain.cycles.events import CycleBlocked as BlockedEvent
                        await event_bus.publish(
                            BlockedEvent(project_id=project_id, reason=e.reason),
                        )
                    return
        except Exception:
            log.exception("BudgetGuard check failed (letting cycle proceed)")

    tracker.update_status(
        cycle_id, CycleStatus.RUNNING,
        started_at=datetime.now().isoformat(timespec="seconds"),
    )

    # Dashboard state
    from theswarm.dashboard import get_dashboard_state
    dash = get_dashboard_state()
    dash.start_cycle(repo)

    # Build progress callback — use ProgressBridge if EventBus is available
    on_progress = None
    if event_bus is not None:
        from theswarm.application.services.progress_bridge import ProgressBridge
        on_progress = ProgressBridge(
            event_bus=event_bus,
            cycle_id=cycle_id,
            project_id=repo,
            dashboard_state=dash,
        )
    else:
        async def on_progress(role: str, message: str) -> None:  # type: ignore[no-redef]
            dash.current_phase = f"{role}: {message[:50]}"
            dash.push_event(role, message)

    try:
        cycle_config = CycleConfig(github_repo=repo)

        # Sprint B C2 — apply project effort profile if we have a registered project
        if project_repo is not None and project_id:
            try:
                from theswarm.application.services.effort_profile import EffortProfile
                project = await project_repo.get(project_id)
                if project is not None:
                    resolved = EffortProfile.apply(project.config)
                    cycle_config.max_dev_retries = resolved.max_retries
                    phase_to_cats = {
                        "po": ("planning", "retrospective", "doc_generation"),
                        "techlead": ("review", "breakdown"),
                        "dev": ("implementation",),
                        "qa": ("doc_generation",),
                    }
                    for phase, model in resolved.models.items():
                        for cat in phase_to_cats.get(phase, ()):
                            cycle_config.model_routing[cat] = model
            except Exception:
                log.exception("EffortProfile.apply failed (using defaults)")

        # Publish CycleStarted event
        if event_bus is not None:
            from theswarm.domain.cycles.events import CycleStarted
            from theswarm.domain.cycles.value_objects import CycleId
            await event_bus.publish(CycleStarted(
                cycle_id=CycleId(cycle_id),
                project_id=repo,
                triggered_by="web",
            ))

        result = await run_daily_cycle(cycle_config, on_progress=on_progress)

        dash.cost_so_far = result.get("cost_usd", 0.0)
        cycle_date = result.get("date", "")
        if cycle_date:
            dash.store_report(cycle_date, result)

        tracker.update_status(
            cycle_id, CycleStatus.COMPLETED,
            result=result,
            completed_at=datetime.now().isoformat(timespec="seconds"),
        )

        # Publish CycleCompleted event
        if event_bus is not None:
            from theswarm.domain.cycles.events import CycleCompleted
            from theswarm.domain.cycles.value_objects import CycleId
            await event_bus.publish(CycleCompleted(
                cycle_id=CycleId(cycle_id),
                project_id=repo,
                total_cost_usd=result.get("cost_usd", 0.0),
                prs_opened=len(result.get("prs", [])),
                prs_merged=sum(
                    1 for r in result.get("reviews", [])
                    if r.get("decision") == "APPROVE"
                ),
            ))

            # F1b — persist report + publish DemoReady
            await _emit_demo_ready(
                event_bus=event_bus,
                report_repo=report_repo,
                base_path=base_path,
                cycle_id=cycle_id,
                repo=repo,
                result=result,
            )

        if callback_url:
            await send_callback(callback_url, {
                "cycle_id": cycle_id,
                "status": "completed",
                "result": result,
            })

    except asyncio.CancelledError:
        tracker.update_status(
            cycle_id, CycleStatus.CANCELLED,
            completed_at=datetime.now().isoformat(timespec="seconds"),
        )
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        log.exception("API cycle %s failed", cycle_id)
        tracker.update_status(
            cycle_id, CycleStatus.FAILED,
            error=error_msg,
            completed_at=datetime.now().isoformat(timespec="seconds"),
        )
        # Publish CycleFailed event
        if event_bus is not None:
            from theswarm.domain.cycles.events import CycleFailed
            from theswarm.domain.cycles.value_objects import CycleId
            await event_bus.publish(CycleFailed(
                cycle_id=CycleId(cycle_id),
                project_id=repo,
                error=error_msg,
            ))
        if callback_url:
            await send_callback(callback_url, {
                "cycle_id": cycle_id,
                "status": "failed",
                "error": error_msg,
            })
    finally:
        dash.end_cycle()
