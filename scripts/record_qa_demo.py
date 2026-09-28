"""Film QA's demo of a feature without spending a cycle: the real captures,
on a local checkout of the target, then the report in the player.

What a cycle's QA does after the merges, and only that: start the target
from the checkout, run its `demo.seed`, walk the declared pages and the
pages the given PRs added (`qa_feature_pages`), record the video, build the
report with its gates — `feature_pages` among them — and store it in a
local TheSwarm, whose repo card and player are then filmed like
scripts/record_v2_demo.py films a real cycle. No Claude call: the unit and
E2E gates read "not run", honestly.

    uv run python scripts/record_qa_demo.py --repo jrechet/concert-tour-app \\
        --workspace tmp/cta/repo --prs 393 391 --name qa-feature-pages

The checkout needs its dependencies in `<workspace>/.venv-swarm` (what QA
installs into on a real cycle). Everything but the video lands in
tmp/demo-qa/.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location("record_v2_demo", ROOT / "scripts" / "record_v2_demo.py")
film = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(film)
film.WORK = ROOT / "tmp" / "demo-qa"
film.PORT = 8098
film.BASE = f"http://127.0.0.1:{film.PORT}"


def _head_sha(repo: str, pr: int) -> str:
    return subprocess.run(
        ["gh", "pr", "view", str(pr), "--repo", repo, "--json", "headRefOid", "-q", ".headRefOid"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


async def capture(repo: str, workspace: str, prs: list[int]) -> dict:
    """QA's captures and report on the checkout — the real functions."""
    from theswarm.agents import qa
    from theswarm.tools.github import GitHubClient

    state = {
        "workspace": workspace,
        "claude": object(),  # the captures make no Claude call
        "github": GitHubClient(repo),
        "prs": [{"number": n, "head_sha": _head_sha(repo, n)} for n in prs],
        "github_repo": repo,
    }
    captures = await qa.run_captures(state)
    # No test run here: the unit gate says so instead of a vacuous 0/0 pass.
    report = await qa.generate_demo_report({
        **state, **captures, "unit_tests_not_run_reason": "a capture-only demo, no cycle",
    })
    return {**captures, **report}


async def store(repo: str, qa_out: dict) -> str:
    """The report a cycle would store, in the local TheSwarm's database."""
    from theswarm.application.services.report_generator import ReportGenerator
    from theswarm.domain.cycles.entities import Cycle
    from theswarm.domain.cycles.value_objects import CycleId, CycleStatus
    from theswarm.infrastructure.persistence.sqlite_repos import init_db
    from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository

    demo = qa_out["demo_report"]
    cycle = Cycle(id=CycleId(f"qa{datetime.now():%m%d%H%M%S}"), project_id=repo,
                  status=CycleStatus.COMPLETED, triggered_by="demo",
                  started_at=datetime.now(timezone.utc))
    report = ReportGenerator().generate(
        cycle, qa_gates=demo.get("quality_gates"), screenshots=demo.get("screenshots") or (),
        videos=demo.get("videos") or (), stories=ReportGenerator.stories_of(demo),
    )
    film.WORK.mkdir(parents=True, exist_ok=True)
    conn = await init_db(str(film.WORK / "theswarm.db"))
    try:
        await SQLiteReportRepository(conn).save(report)
    finally:
        await conn.close()
    return report.id


def film_report(p, repo: str, report_id: str, gate: dict, feature_shots: list[dict] = ()) -> Path:
    browser, context, video_dir = film._film(p, "qa")
    page = context.new_page()
    page.goto(f"{film.BASE}/r/{repo}", wait_until="domcontentloaded")
    card = page.locator('[data-testid="latest-demo"]')
    if card.count():
        card.scroll_into_view_if_needed()
    film._caption(page, "QA ran on the target: its demo.seed filled the database, then the walk")
    time.sleep(5)
    page.goto(f"{film.BASE}/demos/{report_id}/play", wait_until="domcontentloaded")
    film._caption(page, f"feature pages: {gate.get('status')} — {gate.get('reason', '')}")
    time.sleep(4)
    for _ in range(12):
        if page.locator("video:visible").count():
            try:
                page.locator("video:visible").first.evaluate("v => { v.muted = true; v.play(); }")
            except Exception:  # noqa: BLE001
                pass
            time.sleep(10)
        else:
            time.sleep(4)
        page.keyboard.press("ArrowRight")
    for shot in feature_shots:  # the feature's own pages, full size
        page.goto(f"{film.BASE}/artifacts/{shot['path']}", wait_until="domcontentloaded")
        film._caption(page, f"{shot['label']} — captured by QA on the running target")
        time.sleep(5)
    return film._close(browser, context, video_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--workspace", required=True, help="a checkout of the target")
    ap.add_argument("--prs", type=int, nargs="+", required=True, help="the PRs the feature is in")
    ap.add_argument("--name", required=True, help="docs/demos/<name>.webm")
    args = ap.parse_args()

    workspace = str(Path(args.workspace).resolve())
    import os

    os.environ.setdefault("GITHUB_TOKEN", film._env()["GITHUB_TOKEN"])  # QA reads the PRs' diffs
    qa_out = asyncio.run(capture(args.repo, workspace, args.prs))
    gate = qa_out["demo_report"]["quality_gates"].get("feature_pages", {})
    print("feature pages gate:", json.dumps(gate), flush=True)
    report_id = asyncio.run(store(args.repo, qa_out))

    server = film._start_server(film._env())
    try:
        with sync_playwright() as p:
            shots = [s for s in qa_out["demo_report"].get("screenshots", [])
                     if str(s.get("label", "")).startswith("feature_pr_")]
            video = film_report(p, args.repo, report_id, gate, shots)
        out = film.DEMOS_DIR / f"{args.name}.webm"
        film.join([video], out)
    finally:
        server.terminate()
        server.wait(timeout=20)
    summary = {"report": report_id, "feature_pages": gate,
               "screenshots": [s.get("label") for s in qa_out["demo_report"].get("screenshots", [])],
               "video": str(out.relative_to(ROOT)), "bytes": out.stat().st_size}
    (film.WORK / f"{args.name}.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0 if gate.get("status") == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
