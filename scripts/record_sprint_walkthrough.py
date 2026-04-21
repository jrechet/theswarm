"""Record a walkthrough webm for any sprint into docs/demos/sprint-<L>.webm.

Starts an isolated TheSwarm server with seed-self data (so every sprint has
a rich demos list), then drives Playwright through the core dashboard surfaces
while recording video. The per-sprint difference is the demo page it lingers on.

Usage:
    uv run python scripts/record_sprint_walkthrough.py <letter>
    uv run python scripts/record_sprint_walkthrough.py B
    uv run python scripts/record_sprint_walkthrough.py all   # B-F
"""

from __future__ import annotations

import multiprocessing
import os
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DEMOS_DIR = ROOT / "docs" / "demos"
DEFAULT_PORT = 8096


def _run_server(db_path: str, artifact_dir: str, port: int) -> None:
    import asyncio

    os.environ["SWARM_SKIP_SELF_SEED"] = ""  # let the server auto-seed
    from theswarm.presentation.web.server import start_server

    asyncio.run(start_server(
        host="127.0.0.1",
        port=port,
        db_path=db_path,
        artifact_dir=artifact_dir,
    ))


def _wait_for_server(base_url: str, timeout_s: int = 45) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base_url}/health", timeout=1)
            return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("server did not start in time")


def _walk(tmpdir: Path, base_url: str, sprint_letter: str) -> Path:
    video_dir = tmpdir / "videos"
    video_dir.mkdir(parents=True, exist_ok=True)

    sprint_id = f"theswarm-sprint-{sprint_letter.lower()}"

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
            ("/projects/theswarm", 3.0),
            ("/cycles/", 2.5),
            ("/demos/", 2.5),
            (f"/demos/{sprint_id}/play", 6.0),
            ("/features/", 2.5),
            ("/health", 1.5),
        ]
        for path, hold in stops:
            try:
                page.goto(f"{base_url}{path}", timeout=20_000)
                page.wait_for_load_state("domcontentloaded")
            except Exception as exc:
                print(f"warn: {path}: {exc}", file=sys.stderr)
            time.sleep(hold)

        context.close()
        browser.close()

    webms = list(video_dir.glob("*.webm"))
    if not webms:
        raise RuntimeError("Playwright did not produce a webm")
    return webms[0]


def _record_one(sprint_letter: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix=f"sprint-{sprint_letter.lower()}-record-"))
    db_path = str(tmp / "seed.db")
    artifact_dir = str(tmp / "artifacts")
    os.makedirs(artifact_dir, exist_ok=True)

    port = DEFAULT_PORT
    base_url = f"http://127.0.0.1:{port}"

    proc = multiprocessing.Process(
        target=_run_server, args=(db_path, artifact_dir, port), daemon=True,
    )
    proc.start()
    try:
        _wait_for_server(base_url)
        source = _walk(tmp, base_url, sprint_letter)
        out_path = DEMOS_DIR / f"sprint-{sprint_letter.upper()}.webm"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, out_path)
        size = out_path.stat().st_size
        print(f"wrote {out_path.relative_to(ROOT)} ({size} bytes)")
        return out_path
    finally:
        proc.terminate()
        proc.join(timeout=5)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: record_sprint_walkthrough.py <letter|all>", file=sys.stderr)
        return 2

    arg = sys.argv[1].strip().upper()
    letters = ["B", "C", "D", "E", "F"] if arg == "ALL" else [arg]

    for letter in letters:
        if letter not in "ABCDEFG":
            print(f"skip unknown sprint: {letter}", file=sys.stderr)
            continue
        _record_one(letter)

    return 0


if __name__ == "__main__":
    sys.exit(main())
