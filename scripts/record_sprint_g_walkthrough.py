"""Record a Sprint G walkthrough video for docs/demos/sprint-G.webm.

Boots an isolated TheSwarm server, seeds one failed cycle with checkpoints
(so the G5 Resume UI shows), then drives a Playwright browser through the
key Sprint G surfaces while recording video.

Usage:
    uv run python scripts/record_sprint_g_walkthrough.py
"""

from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "docs" / "demos" / "sprint-G.webm"
PORT = 8097
BASE_URL = f"http://127.0.0.1:{PORT}"

PROJECT_ID = "sprint-g-demo"
FAILED_CYCLE_ID = str(uuid.uuid4())


def _run_server(db_path: str, artifact_dir: str) -> None:
    import asyncio

    from theswarm.presentation.web.server import start_server

    asyncio.run(start_server(
        host="127.0.0.1",
        port=PORT,
        db_path=db_path,
        artifact_dir=artifact_dir,
    ))


def _seed(db_path: str) -> None:
    """Seed one project, one failed cycle, and checkpoints so /cycles/<id> shows Resume."""
    now = datetime.now(timezone.utc)
    started = now.isoformat()

    # Wait until the schema has been created by the server.
    for _ in range(60):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cycle_checkpoints'")
            if cur.fetchone():
                break
            conn.close()
        except sqlite3.OperationalError:
            pass
        time.sleep(0.25)
    else:
        raise RuntimeError("schema did not appear in time")

    # Project
    cur.execute(
        """INSERT OR REPLACE INTO projects
           (id, repo, default_branch, framework, ticket_source,
            team_channel, schedule, test_command, source_dir,
            config_json, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (PROJECT_ID, "demo/sprint-g", "main", "fastapi", "github",
         "#swarm-demo", "", "", "src/",
         json.dumps({"effort": "medium"}), started, started),
    )

    # Failed cycle with 3 phase rows: po_morning ok, techlead_breakdown ok, dev_loop failed
    phases = [
        {
            "phase": "po_morning", "agent": "po",
            "started_at": started, "completed_at": started,
            "status": "completed", "tokens_used": 1200,
            "cost_usd": 0.04, "summary": "Selected 3 backlog stories",
        },
        {
            "phase": "techlead_breakdown", "agent": "techlead",
            "started_at": started, "completed_at": started,
            "status": "completed", "tokens_used": 2800,
            "cost_usd": 0.11, "summary": "Split into dev-ready sub-tasks",
        },
        {
            "phase": "dev_loop", "agent": "dev",
            "started_at": started, "completed_at": started,
            "status": "failed", "tokens_used": 5400,
            "cost_usd": 0.22, "summary": "Transient GitHub 502 on push",
        },
    ]
    budgets = [{"role": "claude", "limit": 200000, "used": 9400}]
    cur.execute(
        """INSERT OR REPLACE INTO cycles
           (id, project_id, status, triggered_by, started_at, completed_at,
            total_tokens, total_cost_usd, prs_opened_json, prs_merged_json,
            phases_json, budgets_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (FAILED_CYCLE_ID, PROJECT_ID, "failed", "web", started, started,
         9400, 0.37, json.dumps([]), json.dumps([]),
         json.dumps(phases), json.dumps(budgets)),
    )

    # Checkpoints: the last ok one is techlead_breakdown -> next_phase = dev_loop
    for phase, ok in (("po_morning", 1), ("techlead_breakdown", 1), ("dev_loop", 0)):
        cur.execute(
            """INSERT OR REPLACE INTO cycle_checkpoints
               (cycle_id, phase, state_json, ok, completed_at)
               VALUES (?, ?, ?, ?, ?)""",
            (FAILED_CYCLE_ID, phase, json.dumps({"phase": phase}), ok, started),
        )

    conn.commit()
    conn.close()


def _wait_for_server() -> None:
    for _ in range(60):
        try:
            urllib.request.urlopen(f"{BASE_URL}/health", timeout=1)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("server did not start in time")


def _walk(tmpdir: Path) -> Path:
    video_dir = tmpdir / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(video_dir),
            record_video_size={"width": 1280, "height": 720},
        )
        page = context.new_page()

        stops = [
            ("/", 3.5),
            ("/projects/", 2.5),
            ("/cycles/", 2.5),
            (f"/cycles/{FAILED_CYCLE_ID}", 5.0),
            ("/demos/", 2.5),
            ("/features/", 3.0),
            ("/health", 1.5),
        ]
        for path, hold in stops:
            page.goto(f"{BASE_URL}{path}")
            page.wait_for_load_state("domcontentloaded")
            time.sleep(hold)

        context.close()
        browser.close()

    webms = list(video_dir.glob("*.webm"))
    if not webms:
        raise RuntimeError("Playwright did not produce a webm")
    return webms[0]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="sprint-g-record-"))
    db_path = str(tmp / "seed.db")
    artifact_dir = str(tmp / "artifacts")
    os.makedirs(artifact_dir, exist_ok=True)

    proc = multiprocessing.Process(
        target=_run_server, args=(db_path, artifact_dir), daemon=True,
    )
    proc.start()
    try:
        _wait_for_server()
        _seed(db_path)
        source = _walk(tmp)
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, OUT_PATH)
        size = OUT_PATH.stat().st_size
        print(f"wrote {OUT_PATH.relative_to(ROOT)} ({size} bytes)")
    finally:
        proc.terminate()
        proc.join(timeout=5)
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
