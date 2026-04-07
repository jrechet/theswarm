"""Live cycle dashboard — SSE endpoint + HTML page.

Serves a real-time dashboard at /swarm/dashboard showing:
- Current cycle status and phase
- Cost tracking
- PR activity
- Historical data from cycle-history.jsonl
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, StreamingResponse

log = logging.getLogger(__name__)


class DashboardState:
    """Shared mutable state for the dashboard SSE feed."""

    def __init__(self) -> None:
        self.cycle_running: bool = False
        self.current_phase: str = ""
        self.current_repo: str = ""
        self.cycle_start: str = ""
        self.cost_so_far: float = 0.0
        self.events: list[dict[str, str]] = []
        self._subscribers: list[asyncio.Queue] = []
        self.github_repo: str = ""  # set by gateway for history queries
        self.reports: dict[str, dict] = {}  # date -> cycle result dict
        self.base_url: str = ""  # external URL for report action endpoints

    def push_event(self, role: str, message: str) -> None:
        event = {
            "role": role,
            "message": message,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
        }
        self.events.append(event)
        # Keep last 100 events
        if len(self.events) > 100:
            self.events = self.events[-100:]
        # Notify SSE subscribers
        data = json.dumps(event)
        for q in self._subscribers:
            try:
                q.put_nowait(data)
            except asyncio.QueueFull:
                pass

    def start_cycle(self, repo: str) -> None:
        self.cycle_running = True
        self.current_repo = repo
        self.cycle_start = datetime.now().strftime("%H:%M:%S")
        self.cost_so_far = 0.0
        self.events = []

    def end_cycle(self) -> None:
        self.cycle_running = False
        self.current_phase = ""

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers = [s for s in self._subscribers if s is not q]

    def store_report(self, date: str, result: dict) -> None:
        """Store a cycle result for later report serving."""
        self.reports[date] = result
        # Keep last 30 reports
        if len(self.reports) > 30:
            oldest = sorted(self.reports.keys())[0]
            del self.reports[oldest]

    def to_json(self) -> dict[str, Any]:
        return {
            "cycle_running": self.cycle_running,
            "current_phase": self.current_phase,
            "current_repo": self.current_repo,
            "cycle_start": self.cycle_start,
            "cost_so_far": round(self.cost_so_far, 4),
            "recent_events": self.events[-20:],
        }


# Singleton
_state = DashboardState()


def get_dashboard_state() -> DashboardState:
    return _state


def register_dashboard_routes(app) -> None:
    """Register dashboard routes on a FastAPI app."""

    @app.get("/swarm/dashboard")
    async def dashboard_page():
        return HTMLResponse(content=_DASHBOARD_HTML)

    @app.get("/swarm/dashboard/state")
    async def dashboard_state():
        return _state.to_json()

    @app.get("/swarm/dashboard/history")
    async def dashboard_history():
        if not _state.github_repo:
            return {"history": [], "note": "No repo configured"}
        try:
            from theswarm.tools.github import GitHubClient
            from theswarm.cycle_log import read_cycle_history
            github = GitHubClient(_state.github_repo)
            entries = await read_cycle_history(github, limit=50)
            return {"history": entries}
        except Exception:
            log.exception("Dashboard: failed to read cycle history")
            return {"history": [], "error": "Failed to read history"}

    @app.get("/swarm/dashboard/events")
    async def dashboard_sse(request: Request):
        queue = _state.subscribe()

        async def event_stream():
            try:
                # Send current state as first event
                yield f"data: {json.dumps(_state.to_json())}\n\n"
                while True:
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=30)
                        yield f"data: {data}\n\n"
                    except asyncio.TimeoutError:
                        # Send keepalive
                        yield ": keepalive\n\n"
                    if await request.is_disconnected():
                        break
            finally:
                _state.unsubscribe(queue)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── Report endpoints ─────────────────────────────────────────────
    # NOTE: /weekly must be registered before /{date} to avoid path collision.

    @app.get("/swarm/reports/weekly")
    async def weekly_report():
        """Serve a weekly summary report from cycle history."""
        try:
            from theswarm.tools.github import GitHubClient
            from theswarm.cycle_log import read_cycle_history
            from theswarm.report import generate_weekly_summary

            if not _state.github_repo:
                return HTMLResponse(content="<h1>No repo configured</h1>", status_code=404)
            github = GitHubClient(_state.github_repo)
            entries = await read_cycle_history(github, limit=7)
            html = generate_weekly_summary(entries)
            return HTMLResponse(content=html)
        except Exception:
            log.exception("Failed to generate weekly report")
            return HTMLResponse(content="<h1>Error generating weekly report</h1>", status_code=500)

    @app.get("/swarm/reports/{date}")
    async def report_page(date: str):
        """Serve an HTML report for a given cycle date."""
        result = _state.reports.get(date)
        if not result:
            return HTMLResponse(
                content=f"<h1>No report for {date}</h1><p>Cycle may not have run or report expired.</p>",
                status_code=404,
            )
        from theswarm.report import generate_cycle_report
        html = generate_cycle_report(result, base_url=_state.base_url)
        return HTMLResponse(content=html)

    @app.post("/swarm/reports/{date}/approve/{pr_number}")
    async def approve_pr(date: str, pr_number: int):
        """Approve and merge a PR from the report."""
        if not _state.github_repo:
            return HTMLResponse(content="<h1>No repo configured</h1>", status_code=400)
        try:
            from theswarm.tools.github import GitHubClient
            github = GitHubClient(_state.github_repo)
            await github.merge_pr(pr_number)
            return HTMLResponse(
                content=f"<h1>PR #{pr_number} merged.</h1>"
                f'<p><a href="/swarm/reports/{date}">Back to report</a></p>',
            )
        except Exception as e:
            log.exception("Failed to merge PR #%d", pr_number)
            return HTMLResponse(
                content=f"<h1>Failed to merge PR #{pr_number}</h1><p>{e}</p>",
                status_code=500,
            )

    @app.post("/swarm/reports/{date}/comment/{pr_number}")
    async def comment_on_pr(date: str, pr_number: int, request: Request):
        """Post a review comment on a PR from the report."""
        if not _state.github_repo:
            return HTMLResponse(content="<h1>No repo configured</h1>", status_code=400)
        try:
            form = await request.form()
            comment = form.get("comment", "")
            if not comment:
                return HTMLResponse(
                    content="<h1>No comment provided</h1>"
                    f'<p><a href="/swarm/reports/{date}">Back to report</a></p>',
                    status_code=400,
                )
            from theswarm.tools.github import GitHubClient
            github = GitHubClient(_state.github_repo)
            await github.create_pr_comment(pr_number, str(comment))
            return HTMLResponse(
                content=f"<h1>Comment posted on PR #{pr_number}.</h1>"
                f'<p><a href="/swarm/reports/{date}">Back to report</a></p>',
            )
        except Exception as e:
            log.exception("Failed to comment on PR #%d", pr_number)
            return HTMLResponse(
                content=f"<h1>Failed to comment on PR #{pr_number}</h1><p>{e}</p>",
                status_code=500,
            )


_DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TheSwarm Dashboard</title>
<style>
  :root {
    --bg: #0a0a0f;
    --surface: #12121a;
    --border: #1e1e2e;
    --text: #e0e0e6;
    --text-dim: #8888a0;
    --accent: #00ccff;
    --green: #00cc88;
    --red: #ff4466;
    --yellow: #ffaa00;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: 'SF Mono', 'Fira Code', monospace;
    background: var(--bg);
    color: var(--text);
    padding: 2rem;
    line-height: 1.5;
  }
  h1 { color: var(--accent); font-size: 1.4rem; margin-bottom: 1.5rem; }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 1.5rem; }
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.2rem;
  }
  .card h2 { font-size: 0.85rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.8rem; }
  .big-number { font-size: 2rem; font-weight: 700; }
  .status-badge {
    display: inline-block;
    padding: 0.2rem 0.6rem;
    border-radius: 4px;
    font-size: 0.8rem;
    font-weight: 600;
  }
  .status-running { background: var(--accent); color: var(--bg); }
  .status-idle { background: var(--border); color: var(--text-dim); }
  .event-log {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 1.2rem;
    max-height: 400px;
    overflow-y: auto;
  }
  .event-log h2 { font-size: 0.85rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.8rem; }
  .event {
    padding: 0.3rem 0;
    border-bottom: 1px solid var(--border);
    font-size: 0.85rem;
  }
  .event:last-child { border-bottom: none; }
  .event-time { color: var(--text-dim); }
  .event-role { color: var(--accent); font-weight: 600; }
  .cost { color: var(--green); }
  @media (max-width: 600px) { .grid { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<h1>TheSwarm Dashboard</h1>
<div class="grid">
  <div class="card">
    <h2>Cycle Status</h2>
    <div id="status"><span class="status-badge status-idle">Idle</span></div>
    <div id="phase" style="margin-top:0.5rem;color:var(--text-dim)"></div>
    <div id="repo" style="margin-top:0.3rem;font-size:0.85rem;color:var(--text-dim)"></div>
  </div>
  <div class="card">
    <h2>Cost (this cycle)</h2>
    <div class="big-number cost" id="cost">$0.00</div>
    <div id="start-time" style="margin-top:0.5rem;font-size:0.85rem;color:var(--text-dim)"></div>
  </div>
</div>
<div class="event-log">
  <h2>Live Events</h2>
  <div id="events"><div class="event" style="color:var(--text-dim)">Waiting for cycle...</div></div>
</div>
<script>
const eventsEl = document.getElementById('events');
const statusEl = document.getElementById('status');
const phaseEl = document.getElementById('phase');
const repoEl = document.getElementById('repo');
const costEl = document.getElementById('cost');
const startEl = document.getElementById('start-time');

function updateState(state) {
  if (state.cycle_running) {
    statusEl.innerHTML = '<span class="status-badge status-running">Running</span>';
    phaseEl.textContent = state.current_phase || '';
    repoEl.textContent = state.current_repo || '';
    costEl.textContent = '$' + state.cost_so_far.toFixed(2);
    startEl.textContent = state.cycle_start ? 'Started: ' + state.cycle_start : '';
  } else {
    statusEl.innerHTML = '<span class="status-badge status-idle">Idle</span>';
    phaseEl.textContent = '';
  }
  if (state.recent_events && state.recent_events.length > 0) {
    eventsEl.innerHTML = '';
    state.recent_events.forEach(addEvent);
  }
}

function addEvent(ev) {
  const div = document.createElement('div');
  div.className = 'event';
  div.innerHTML = '<span class="event-time">' + (ev.timestamp || '') + '</span> '
    + '<span class="event-role">[' + ev.role + ']</span> '
    + ev.message;
  eventsEl.prepend(div);
  while (eventsEl.children.length > 50) eventsEl.lastChild.remove();
}

// SSE connection with auto-reconnect
function connect() {
  const es = new EventSource('/swarm/dashboard/events');
  es.onmessage = function(e) {
    try {
      const data = JSON.parse(e.data);
      if (data.recent_events) {
        updateState(data);
      } else if (data.role) {
        addEvent(data);
      }
    } catch(err) {}
  };
  es.onerror = function() {
    es.close();
    setTimeout(connect, 3000);
  };
}

// Initial state fetch
fetch('/swarm/dashboard/state')
  .then(r => r.json())
  .then(updateState)
  .catch(() => {});

connect();
</script>
</body>
</html>
"""
