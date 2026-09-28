"""Record the V2 flow end to end into docs/demos/<name>.webm — a real cycle.

"Do this feature, create the demo, show the demo to the user": the script
drives the product the way the owner does, in a browser, on a local server,
against a real repository.

  1. filmed — the repo picker, the repo page, a feature typed into the
     composer, the issue it creates, ▶ Play, and the theater live for a
     while;
  2. not filmed — the cycle builds, reviews, merges, runs QA and writes its
     demo (15 to 25 minutes);
  3. filmed — the theater once done, the repo's latest-demo card, and the
     demo player walked slide by slide (stories, QA gates, the video QA
     recorded of the app).

The two films are joined into one webm. It spends real subscription time
and merges real PRs on the target, like a harness run.

With `--harness-feature <id>` the first film is replaced by the eval
harness itself (`scripts/cycle_e2e.py`, run against this local server, its
history kept in tmp/demo-v2/): the demo then shows what the harness
judged — the reliability panel on the repo page, and QA's gates in the
player.

    uv run python scripts/record_v2_demo.py \\
        --repo jrechet/concert-tour-app --name v2-play-to-demo \\
        --feature "Show how full a concert is" \\
        --body "GET /api/v1/concerts/{id}/occupancy returns …"

Needs `.env` at the repository root (or SWARM_ENV_FILE) with GITHUB_TOKEN,
and the stylesheet built (`bash scripts/build-css.sh`) or the pages film
unstyled;
the Claude identity is the laptop's subscription (`python -m theswarm
validate` must say identity=subscription). Everything but the video lands in
tmp/demo-v2/ (ignored by git).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
DEMOS_DIR = ROOT / "docs" / "demos"
WORK = ROOT / "tmp" / "demo-v2"
PORT = 8095
BASE = f"http://127.0.0.1:{PORT}"
VIEWPORT = {"width": 1280, "height": 720}
TERMINAL = {"completed", "failed", "cancelled"}


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env_file = Path(os.environ.get("SWARM_ENV_FILE", ROOT / ".env"))
    if not env_file.exists():
        env_file = ROOT.parent.parent.parent / ".env"  # a worktree: the main checkout's
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() and not key.startswith("#"):
                env.setdefault(key.strip(), value.strip().strip('"'))
    env.pop("ANTHROPIC_API_KEY", None)  # the subscription only (V2 invariant I1)
    env.update({
        "SWARM_AUTH_DISABLED": "1",
        "SWARM_CLAUDE_BACKEND": "sdk",
        "SWARM_SKIP_SELF_SEED": "1",
        "SWARM_WORKSPACE_DIR": str(WORK / "workspaces"),
        "SWARM_DEV_PARALLELISM": env.get("SWARM_DEV_PARALLELISM", "2"),
        "BASE_PATH": "",
    })
    if not env.get("GITHUB_TOKEN"):
        sys.exit("GITHUB_TOKEN is not set (.env or environment)")
    return env


def _get(path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as resp:
            return resp.status, resp.read().decode()
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc)


def _start_server(env: dict[str, str]) -> subprocess.Popen:
    WORK.mkdir(parents=True, exist_ok=True)
    if _get("/health")[0]:
        # Something else answers there: its /health would pass for ours, and
        # the film would be of a stranger (OrbStack held 8096 on the laptop).
        sys.exit(f"port {PORT} is taken by another server — pick another one")
    log = open(WORK / "server.log", "a")
    proc = subprocess.Popen(
        [str(ROOT / ".venv" / "bin" / "python"), "-m", "theswarm", "serve",
         "--port", str(PORT), "--db", str(WORK / "theswarm.db")],
        cwd=ROOT, env={**env, "PYTHONPATH": str(ROOT / "src")},
        stdout=log, stderr=subprocess.STDOUT,
    )
    for _ in range(180):
        if _get("/health")[0] == 200:
            return proc
        if proc.poll() is not None:
            sys.exit(f"the server exited — see {WORK / 'server.log'}")
        time.sleep(1)
    proc.terminate()
    sys.exit("the server did not answer /health in 3 minutes")


def _film(p, name: str):
    video_dir = WORK / "videos" / name
    shutil.rmtree(video_dir, ignore_errors=True)
    video_dir.mkdir(parents=True)
    browser = p.chromium.launch()
    context = browser.new_context(viewport=VIEWPORT, record_video_dir=str(video_dir),
                                  record_video_size=VIEWPORT)
    return browser, context, video_dir


def _caption(page, text: str) -> None:
    """A caption strip at the bottom of the frame, for the viewer."""
    page.evaluate(
        """text => {
            let el = document.getElementById('demo-caption');
            if (!el) {
                el = document.createElement('div');
                el.id = 'demo-caption';
                el.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:99999;'
                    + 'padding:14px 24px;background:rgba(20,18,14,.86);color:#fff;'
                    + 'font:600 18px/1.35 system-ui,sans-serif;letter-spacing:.01em';
                document.body.appendChild(el);
            }
            el.textContent = text;
        }""",
        text,
    )


def _close(browser, context, video_dir: Path) -> Path:
    context.close()
    browser.close()
    (video,) = list(video_dir.glob("*.webm"))
    return video


def film_play(p, repo: str, feature: str, body: str, theater_seconds: int) -> tuple[Path, str]:
    """Picker → repo → composer → issue → ▶ Play → theater. Returns (video, cycle id)."""
    browser, context, video_dir = _film(p, "play")
    page = context.new_page()
    page.goto(f"{BASE}/", wait_until="domcontentloaded")
    time.sleep(3)
    page.click(f'a[href$="/r/{repo}"]')
    page.wait_for_load_state("domcontentloaded")
    time.sleep(3)
    page.click("#composer-body")
    page.type("#composer-body", f"{feature}\n{body}", delay=18)
    time.sleep(1.5)
    page.click('[data-testid="composer"] button[type="submit"]')
    page.wait_for_load_state("domcontentloaded")
    row = page.locator('[data-testid="fresh-issue"]', has_text=feature).first
    row.scroll_into_view_if_needed()
    time.sleep(2.5)
    row.locator('button:has-text("Play")').click()
    page.wait_for_url(re.compile(r".*/c/[0-9a-f]{12}"), timeout=60_000)
    cycle_id = page.url.rstrip("/").rsplit("/", 1)[-1]
    print(f"cycle {cycle_id} started — filming the theater for {theater_seconds}s", flush=True)
    time.sleep(theater_seconds)
    return _close(browser, context, video_dir), cycle_id


def wait_for_cycle(cycle_id: str, budget_s: int) -> dict:
    deadline = time.time() + budget_s
    last = ""
    while time.time() < deadline:
        status, text = _get(f"/api/cycles/{cycle_id}")
        body = json.loads(text) if status == 200 else {}
        state = str(body.get("status", ""))
        if state != last:
            print(f"  [{time.strftime('%H:%M:%S')}] {state}", flush=True)
            last = state
        if state in TERMINAL:
            return body
        time.sleep(30)
    sys.exit(f"cycle {cycle_id} did not finish in {budget_s}s")


def film_demo(p, repo: str, cycle_id: str) -> tuple[Path, str]:
    """Theater once done → latest-demo card → the demo player, slide by slide."""
    browser, context, video_dir = _film(p, "demo")
    page = context.new_page()
    page.goto(f"{BASE}/c/{cycle_id}", wait_until="domcontentloaded")
    _caption(page, "The cycle is over: the theater shows who did what")
    time.sleep(6)
    page.goto(f"{BASE}/r/{repo}", wait_until="domcontentloaded")
    evals_panel = page.locator('[data-testid="evals"]')
    if evals_panel.count():
        evals_panel.scroll_into_view_if_needed()
        _caption(page, "The harness's verdict: built, and judged on the running app")
        time.sleep(6)
    card = page.locator('[data-testid="latest-demo"]')
    play_url = ""
    if card.count():
        card.scroll_into_view_if_needed()
        _caption(page, "The demo QA recorded, on the repo page")
        time.sleep(4)
        link = card.locator('a[href*="/demos/"]').first
        play_url = link.get_attribute("href") or ""
    if play_url:
        page.goto(f"{BASE}{play_url}" if play_url.startswith("/") else play_url,
                  wait_until="domcontentloaded")
        time.sleep(3)
        for _ in range(14):  # stories, gates, screenshots, video
            if page.locator("video:visible").count():
                try:
                    page.locator("video:visible").first.evaluate("v => { v.muted = true; v.play(); }")
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(9)
            else:
                time.sleep(3.5)
            page.keyboard.press("ArrowRight")
    return _close(browser, context, video_dir), play_url


def run_harness(repo: str, feature_id: str, budget: int) -> tuple[str, int]:
    """The eval harness against this local server: it writes the issue,
    starts the cycle, waits, scores it and posts the score here. Returns
    (cycle id, the harness's exit code)."""
    history = WORK / "harness-runs.jsonl"
    history.unlink(missing_ok=True)
    proc = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), "scripts/cycle_e2e.py", "--repo", repo,
         "--feature-id", feature_id, "--budget", str(budget), "--history", str(history)],
        cwd=ROOT, env={**os.environ, "SWARM_BASE": BASE, "SWARM_ACCESS_KEY": "local-demo",
                       "PYTHONPATH": str(ROOT / "src")},
        capture_output=True, text=True,
    )
    print(proc.stdout[-4000:], proc.stderr[-2000:], sep="\n", flush=True)
    lines = history.read_text().splitlines() if history.exists() else []
    if not lines:
        sys.exit("the harness scored nothing — see the output above")
    return json.loads(lines[-1])["cycle_id"], proc.returncode


def join(parts: list[Path], out: Path) -> None:
    """One webm from the films, re-encoded small (VP9, 1280x720)."""
    listing = WORK / "videos" / "parts.txt"
    listing.write_text("".join(f"file '{p}'\n" for p in parts))
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c:v", "libvpx-vp9", "-b:v", "0", "-crf", "42", "-row-mt", "1", "-deadline", "good",
         "-cpu-used", "4", "-an", str(out)],
        check=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--name", required=True, help="docs/demos/<name>.webm")
    ap.add_argument("--feature", default="", help="the issue title (a filmed Play)")
    ap.add_argument("--harness-feature", default="",
                    help="an eval feature id: the harness runs it instead of a filmed Play")
    ap.add_argument("--body", default="", help="the issue body")
    ap.add_argument("--theater-seconds", type=int, default=75)
    ap.add_argument("--budget", type=int, default=3600)
    args = ap.parse_args()

    if not (args.feature or args.harness_feature):
        sys.exit("--feature or --harness-feature is required")

    server = _start_server(_env())
    try:
        with sync_playwright() as p:
            films: list[Path] = []
            harness_exit = None
            if args.harness_feature:
                cycle_id, harness_exit = run_harness(args.repo, args.harness_feature, args.budget)
                result = wait_for_cycle(cycle_id, 60)
            else:
                play_film, cycle_id = film_play(p, args.repo, args.feature, args.body, args.theater_seconds)
                films.append(play_film)
                result = wait_for_cycle(cycle_id, args.budget)
            demo_film, play_url = film_demo(p, args.repo, cycle_id)
            films.append(demo_film)
        out = DEMOS_DIR / f"{args.name}.webm"
        join(films, out)
        summary = {
            "cycle": cycle_id, "status": result.get("status"), "repo": args.repo,
            "feature": args.feature or args.harness_feature, "harness_exit": harness_exit,
            "prs": result.get("prs_opened"), "merged": result.get("prs_merged"),
            "error": result.get("error"), "demo_player": play_url,
            "video": str(out.relative_to(ROOT)), "bytes": out.stat().st_size,
        }
        (WORK / f"{args.name}.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
        return 0 if result.get("status") == "completed" else 1
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    sys.exit(main())
