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

    tracker.update_status(
        cycle_id, CycleStatus.RUNNING,
        started_at=datetime.now().isoformat(timespec="seconds"),
    )

    # Dashboard state
    from theswarm.dashboard import get_dashboard_state
    dash = get_dashboard_state()
    dash.start_cycle(repo)

    try:
        cycle_config = CycleConfig(github_repo=repo)

        async def on_progress(role: str, message: str) -> None:
            dash.current_phase = f"{role}: {message[:50]}"
            dash.push_event(role, message)

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
        if callback_url:
            await send_callback(callback_url, {
                "cycle_id": cycle_id,
                "status": "failed",
                "error": error_msg,
            })
    finally:
        dash.end_cycle()
