#!/usr/bin/env python3
"""Drive a real cycle against prod and assert what it actually produced.

No browser, no clicking: this is the acceptance test for "can the swarm
implement a feature". It asks the running service for a feature the way a
person would, then judges the outcome by what exists on GitHub afterwards.

    scripts/cycle_e2e.py --repo jrechet/concert-tour-app \
        --feature "Show the remaining ticket count on each concert card"

Exit code 0 only when a cycle finished AND a pull request came out of it.
Anything else prints where it stopped and why.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import httpx

BASE = os.environ.get("SWARM_BASE", "https://bots.jrec.fr/swarm")
KEY = os.environ.get("SWARM_ACCESS_KEY", "")
TERMINAL = {"completed", "failed", "cancelled"}


def _api(path: str, payload: dict | None = None) -> tuple[int, dict]:
    """httpx rather than urllib: it ships its own CA bundle, so the harness
    runs the same on a laptop whose system Python has no certificates."""
    headers = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    try:
        with httpx.Client(timeout=60, follow_redirects=False) as client:
            resp = (client.post(f"{BASE}{path}", json=payload, headers=headers)
                    if payload is not None
                    else client.get(f"{BASE}{path}", headers=headers))
        body = resp.text
        return resp.status_code, (json.loads(body) if body.strip() else {})
    except Exception as exc:  # noqa: BLE001 — the harness reports, never raises
        return 0, {"error": str(exc)[:300]}


def _gh(*args: str) -> str:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=120,
    ).stdout.strip()


def create_issue(repo: str, feature: str) -> int:
    """Ask for the feature the way the composer does: free text in."""
    title, _, body = feature.partition("\n")
    out = _gh("issue", "create", "--repo", repo, "--title", title.strip()[:80],
              "--body", body.strip() or title.strip(), "--label", "status:backlog")
    number = int(out.rstrip("/").split("/")[-1])
    print(f"  issue #{number} created: {title.strip()[:70]}")
    return number


def unfinished_children(repo: str, parent: int) -> list[int]:
    """Sub-tasks of `parent` still open and not in review.

    A cycle that delivers two of four sub-tasks has not implemented the
    feature, however cleanly it reports `completed` — so the harness must
    look at the breakdown, not just at the cycle's own verdict.
    """
    raw = _gh("issue", "list", "--repo", repo, "--state", "open",
              "--limit", "60", "--json", "number,body,labels")
    open_issues = json.loads(raw or "[]")
    marker = f"Parent: #{parent}"
    return sorted(
        i["number"] for i in open_issues
        if marker in (i.get("body") or "")
        and "status:review" not in {l["name"] for l in i.get("labels", [])}
    )


def prs_before(repo: str) -> set[int]:
    raw = _gh("pr", "list", "--repo", repo, "--state", "all", "--limit", "60",
              "--json", "number")
    return {p["number"] for p in json.loads(raw or "[]")}


def start_cycle(repo: str, issue: int) -> str:
    status, body = _api("/api/cycle", {"repo": repo, "issue_number": issue})
    if status != 200:
        sys.exit(f"FAIL start: HTTP {status} {body}")
    cycle_id = body.get("cycle_id") or body.get("id") or ""
    if not cycle_id:
        sys.exit(f"FAIL start: no cycle id in {body}")
    print(f"  cycle {cycle_id} started on {repo}#{issue}")
    return cycle_id


def wait_for(cycle_id: str, budget_s: int) -> tuple[str, str]:
    """Poll until terminal. Returns (status, last_phase_seen)."""
    deadline = time.time() + budget_s
    last_seen, last_phase = "", ""
    while time.time() < deadline:
        status, body = _api(f"/api/cycles/{cycle_id}")
        state = str(body.get("status", "")) if status == 200 else ""
        phase = str(body.get("current_phase") or body.get("phase") or "")
        if state and state != last_seen:
            print(f"  [{time.strftime('%H:%M:%S')}] {state}"
                  + (f" ({phase})" if phase else ""))
            last_seen = state
        if phase:
            last_phase = phase
        if state in TERMINAL:
            return state, last_phase
        if not state:
            # The tracker is in memory; a restart makes the cycle vanish.
            return "lost", last_phase
        time.sleep(20)
    return "timeout", last_phase


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--feature", required=True)
    ap.add_argument("--budget", type=int, default=5400, help="seconds")
    args = ap.parse_args()

    if not KEY:
        sys.exit("SWARM_ACCESS_KEY is unset")

    print(f"▶ {args.repo}: {args.feature.splitlines()[0][:70]}")
    seen = prs_before(args.repo)
    issue = create_issue(args.repo, args.feature)
    cycle_id = start_cycle(args.repo, issue)
    state, last_phase = wait_for(cycle_id, args.budget)

    new_prs = sorted(prs_before(args.repo) - seen)
    print(f"\n  cycle      : {state}" + (f" (last phase {last_phase})" if last_phase else ""))
    print(f"  pull req.  : {new_prs or 'none'}")

    for pr in new_prs:
        checks = _gh("pr", "checks", str(pr), "--repo", args.repo)
        if not checks:
            # A repo with no CI configured reports nothing. Reading that as a
            # failure made the first green run look red: concert-tour-app has
            # no workflows, yet both PRs were sound and merged.
            verdict = "no CI configured"
        elif "fail" in checks:
            verdict = "RED"
        else:
            verdict = "green"
        # Not `state`: that name holds the *cycle* result the verdict below
        # depends on. Shadowing it made a passing run print
        # "FAIL — stopped at: MERGED" (cycle d4aad3415e99, which had in fact
        # completed and merged its PR).
        pr_state = _gh("pr", "view", str(pr), "--repo", args.repo,
                       "--json", "state", "--jq", ".state")
        print(f"    #{pr}: {pr_state.lower()}, CI {verdict}")

    left = unfinished_children(args.repo, issue)
    if left:
        print(f"  unfinished : {', '.join(f'#{n}' for n in left)}")

    if state == "completed" and new_prs and not left:
        print("\nPASS — a feature was asked for, and the whole of it was built.")
        return 0

    reasons = []
    if state != "completed":
        reasons.append(f"cycle {state}")
    if not new_prs:
        reasons.append("no pull request produced")
    if left:
        reasons.append(f"{len(left)} sub-task(s) left unbuilt")
    print("\nFAIL — " + "; ".join(reasons))
    return 1


if __name__ == "__main__":
    sys.exit(main())
