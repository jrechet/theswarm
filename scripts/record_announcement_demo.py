"""Film the comment the swarm posts on an issue when its demo is ready —
rendered by GitHub itself, posted nowhere.

The announcement needs the server's public URL, which a laptop does not
have: posting it from here would put a dead localhost link on a real
issue. This builds the exact comment from a stored report (the same
`demo_comment` the server uses), renders it with GitHub's markdown API
(`POST /markdown`, which renders and stores nothing), and films it in an
issue-like frame into docs/demos/<name>.webm.

    uv run python scripts/record_announcement_demo.py \\
        --db tmp/demo-v2/theswarm.db --cycle 7f4f2188cd90 --issue 404 \\
        --public-url https://bots.jrec.fr/swarm --name demo-announced-on-issue
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
WORK = ROOT / "tmp" / "demo-announce"


async def _report(db: str, cycle_id: str):
    from theswarm.infrastructure.persistence.sqlite_repos import init_db
    from theswarm.infrastructure.recording.report_repo import SQLiteReportRepository

    conn = await init_db(db)
    try:
        (report,) = await SQLiteReportRepository(conn).list_by_cycle(cycle_id, limit=1)
        return report
    finally:
        await conn.close()


def _render(markdown: str, repo: str) -> str:
    out = subprocess.run(
        ["gh", "api", "markdown", "-f", f"text={markdown}", "-f", "mode=gfm", "-f", f"context={repo}"],
        capture_output=True, text=True, check=True,
    )
    return out.stdout


def main() -> int:
    from theswarm.application.services.demo_announcer import demo_comment

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--cycle", required=True)
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--repo", default="jrechet/concert-tour-app")
    ap.add_argument("--public-url", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--author", default="jrechet", help="whose token the swarm posts with")
    args = ap.parse_args()

    report = asyncio.run(_report(args.db, args.cycle))
    markdown = demo_comment(report, f"{args.public_url.rstrip('/')}/demos/{report.id}/play")
    rendered = _render(markdown, args.repo)
    WORK.mkdir(parents=True, exist_ok=True)
    page_html = f"""<!doctype html><meta charset="utf-8"><title>Issue #{args.issue}</title>
<style>
 body{{margin:0;background:#fff;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:#1f2328}}
 main{{max-width:880px;margin:48px auto;padding:0 24px}}
 h1{{font-size:28px;font-weight:400;margin:0 0 4px}} h1 span{{color:#59636e}}
 .meta{{color:#59636e;margin-bottom:28px;border-bottom:1px solid #d1d9e0;padding-bottom:16px}}
 .comment{{border:1px solid #d1d9e0;border-radius:6px}}
 .head{{background:#f6f8fa;border-bottom:1px solid #d1d9e0;padding:8px 16px;color:#59636e}}
 .head b{{color:#1f2328}} .body{{padding:16px}} .body a{{color:#0969da}}
 .note{{margin-top:18px;color:#59636e;font-size:12px}}
</style>
<main><h1>Count the concerts per country <span>#{args.issue}</span></h1>
<div class="meta">{html.escape(args.repo)} · the cycle <code>{html.escape(args.cycle)}</code> built it</div>
<div class="comment"><div class="head"><b>{html.escape(args.author)}</b> commented · posted by the swarm with its token</div>
<div class="body">{rendered}</div></div>
<p class="note">Rendered by GitHub's markdown API from the stored report of that cycle — not posted.</p></main>"""
    page_path = WORK / "comment.html"
    page_path.write_text(page_html)

    video_dir = WORK / "video"
    video_dir.mkdir(exist_ok=True)
    for old in video_dir.glob("*.webm"):
        old.unlink()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1280, "height": 720},
                                      record_video_dir=str(video_dir),
                                      record_video_size={"width": 1280, "height": 720})
        page = context.new_page()
        page.goto(page_path.as_uri())
        time.sleep(8)
        context.close()
        browser.close()
    (video,) = list(video_dir.glob("*.webm"))
    out = ROOT / "docs" / "demos" / f"{args.name}.webm"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-c:v", "libvpx-vp9",
                    "-b:v", "0", "-crf", "42", "-row-mt", "1", "-an", str(out)], check=True)
    print(json.dumps({"video": str(out.relative_to(ROOT)), "bytes": out.stat().st_size,
                      "markdown": markdown}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
