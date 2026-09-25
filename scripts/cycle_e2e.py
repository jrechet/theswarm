#!/usr/bin/env python3
"""Drive a real cycle against prod and score what it actually produced.

No browser, no clicking: this is the acceptance test for "can the swarm
implement a feature". It asks the running service for a feature the way a
person would, then judges the outcome by what exists on GitHub afterwards.

    scripts/cycle_e2e.py --repo jrechet/concert-tour-app \
        --feature "Show the remaining ticket count on each concert card"

Since V2 M6 the feature can come from the eval manifest instead
(`evals/<target>.yaml`, see theswarm.evals): with no --feature the
feature of the day is run (one a day, in rotation, skipping the ones the
target already has); --feature-id picks one; --all runs the series. Every
run is scored — PR, its CI, the reviews, cost, duration, files touched —
and appended to docs/harness-runs.jsonl.

Exit code 0 when every cycle finished AND a pull request came out of it,
or when the Dev found every sub-task already on main (`already_delivered`:
nothing measured, a warning, never a regression). Anything else prints
where it stopped and why.
"""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import json
import os
import pathlib
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))
from theswarm import evals  # noqa: E402 — the scoring lives with the app

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


def closed_children(repo: str, parent: int) -> list[int]:
    """Sub-tasks of `parent` already closed. With no PR, each must be one
    the Dev closed as already satisfied — a sub-task closed any other way
    (by hand, as a duplicate) was not built, and does not make the
    feature already delivered."""
    raw = _gh("issue", "list", "--repo", repo, "--state", "closed",
              "--limit", "60", "--json", "number,body")
    marker = f"Parent: #{parent}"
    return sorted(
        i["number"] for i in json.loads(raw or "[]")
        if marker in (i.get("body") or "")
    )


def prs_before(repo: str) -> set[int]:
    raw = _gh("pr", "list", "--repo", repo, "--state", "all", "--limit", "60",
              "--json", "number")
    return {p["number"] for p in json.loads(raw or "[]")}


HEALTH_WAIT_SECONDS = 180


def wait_for_health(budget_s: int = HEALTH_WAIT_SECONDS, *, api=None, sleep=time.sleep) -> bool:
    """True once /health answers 200, False when it never does within budget.

    A deploy's rolling update answers 404 for a couple of minutes; a harness
    dispatched into that window created its issue and then failed to start
    the cycle (run 35873827304, "HTTP 0 … Extra data"). Wait it out first.
    """
    api = api or _api
    deadline = time.time() + budget_s
    while True:
        status, _ = api("/health")
        if status == 200:
            return True
        if time.time() >= deadline:
            return False
        sleep(10)


def start_cycle(repo: str, issue: int) -> str:
    if not wait_for_health():
        sys.exit(f"FAIL start: {BASE}/health never answered 200 in {HEALTH_WAIT_SECONDS}s")
    status, body = _api("/api/cycle", {"repo": repo, "issue_number": issue})
    if status != 200:
        sys.exit(f"FAIL start: HTTP {status} {body}")
    cycle_id = body.get("cycle_id") or body.get("id") or ""
    if not cycle_id:
        sys.exit(f"FAIL start: no cycle id in {body}")
    print(f"  cycle {cycle_id} started on {repo}#{issue}")
    return cycle_id


# A restart interrupts a cycle and the boot resumer continues it under a new
# id, once (cycle_resumer.MAX_RESUME_DEPTH); one spare hop costs nothing.
MAX_RESUME_HOPS = 2


def wait_for(cycle_id: str, budget_s: int, *, api=None, sleep=time.sleep,
             health=None) -> tuple[str, str, str]:
    """Poll until terminal. Returns (status, last_phase_seen, final_cycle_id).

    A deploy during the cycle is the normal case since V2 M4: the service
    answers 404 while no container runs (stop-first rolling update), then
    the interrupted cycle reads 'failed' with ``resumed_as`` — the id it goes
    on under. The first made this loop report "lost", the second "failed",
    for a cycle that was still running.
    """
    api = api or _api
    health = health or (lambda: wait_for_health(api=api, sleep=sleep))
    deadline = time.time() + budget_s
    last_seen, last_phase, hops = "", "", 0
    while time.time() < deadline:
        status, body = api(f"/api/cycles/{cycle_id}")
        state = str(body.get("status", "")) if status == 200 else ""
        phase = str(body.get("current_phase") or body.get("phase") or "")
        if state and state != last_seen:
            print(f"  [{time.strftime('%H:%M:%S')}] {state}"
                  + (f" ({phase})" if phase else ""))
            last_seen = state
        if phase:
            last_phase = phase
        if state in TERMINAL:
            resumed_as = str(body.get("resumed_as") or "")
            if resumed_as and hops < MAX_RESUME_HOPS:
                print(f"  [{time.strftime('%H:%M:%S')}] resumed as {resumed_as} after a restart")
                cycle_id, last_seen, hops = resumed_as, "", hops + 1
                continue
            return state, last_phase, cycle_id
        if not state:
            if status != 404 or body.get("error") != "not found":
                # No container behind the proxy: a deploy is rolling. Wait
                # for the new one, then ask again.
                if health():
                    sleep(20)
                    continue
            # The service answers and does not know the cycle.
            return "lost", last_phase, cycle_id
        sleep(20)
    return "timeout", last_phase, cycle_id


def build_result(repo: str, passed: bool, state: str, new_prs: list[int], left: list[int]) -> dict:
    return {
        "repo": repo,
        "passed": passed,
        "state": state,
        "prs": new_prs,
        "unfinished": left,
    }


def post_run(record: dict) -> bool:
    """Send the scored record to the swarm (POST /api/evals/runs), where the
    repo page reads the trend. The jsonl line is still written, but its
    push to main is refused by branch protection; this is the live copy."""
    status, body = _api("/api/evals/runs", record)
    if status == 201:
        print(f"  recorded   : run #{body.get('id')} on {BASE}")
        return True
    print(f"  (run not recorded on the API: HTTP {status} {str(body)[:120]})")
    return False


def pr_files(repo: str, pr: int) -> list[str]:
    raw = _gh("pr", "view", str(pr), "--repo", repo, "--json", "files", "--jq", ".files[].path")
    return [line.strip() for line in raw.splitlines() if line.strip()]


def ci_verdict(checks_output: str) -> str:
    """`gh pr checks` output → green | RED | none.

    A repo with no CI configured reports nothing. Reading that as a failure
    made the first green run look red: concert-tour-app has no workflows,
    yet both PRs were sound and merged.
    """
    if not checks_output.strip():
        return "none"
    return "RED" if "fail" in checks_output else "green"


def duration_seconds(started_at: str, completed_at: str) -> float:
    """Seconds between two ISO timestamps; 0 when either is missing or odd."""
    try:
        start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return 0.0
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max(0.0, (end - start).total_seconds())


def review_decisions(result: dict) -> list[str]:
    return [str(r.get("decision", "")) for r in (result or {}).get("reviews", []) or []]


def failure_reasons(state: str, *, new_prs, left, error: str = "") -> list[str]:
    """What the FAIL line says. The cycle's own error comes with its state:
    "cycle failed" alone sent the reader to Seq for 46ff31375dce, which a
    second deploy had killed and the resumer rightly left alone."""
    reasons = []
    if state != "completed":
        reasons.append(f"cycle {state}" + (f": {error}" if error else ""))
    if not new_prs:
        reasons.append("no pull request produced")
    if left:
        reasons.append(f"{len(left)} sub-task(s) left unbuilt")
    return reasons


def cycle_record(cycle_id: str) -> dict:
    status, body = _api(f"/api/cycles/{cycle_id}")
    return body if status == 200 and isinstance(body, dict) else {}


async def alert_mattermost(text: str) -> bool:
    """Post a failed run to the swarm's Mattermost channel, when configured.

    MATTERMOST_URL and MATTERMOST_BOT_TOKEN come from the workflow's
    secrets; without them the alert is a line in the job log, nothing more.
    """
    url = os.environ.get("MATTERMOST_URL", "").strip()
    token = os.environ.get("MATTERMOST_BOT_TOKEN", "").strip()
    channel = os.environ.get("MATTERMOST_CHANNEL", "swarm-bots-logs").strip()
    if not url or not token:
        return False
    try:
        from theswarm_common.chat.mattermost import MattermostAdapter
        from theswarm_common.config import MattermostConfig

        adapter = MattermostAdapter(MattermostConfig(base_url=url, bot_token=token, channel_name=channel))
        await adapter.connect()
        await adapter.post_message(channel, text)
        return True
    except Exception as exc:  # noqa: BLE001 — an alert that fails is a log line
        # Name the server: "404 page not found" alone is Traefik saying no
        # container answers for that host, which reads like a bad path.
        print(f"  (mattermost alert to {url} failed: {str(exc).strip()[:200]})")
        return False


def append_result(path: pathlib.Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(result) + "\n")


PAST_RUNS_LIMIT = 500


def past_runs(repo: str, history: pathlib.Path, *, api=None) -> list[dict]:
    """Every scored run on `repo`, oldest first.

    The API is the live copy: every run posts there. The jsonl is the
    fallback, and a stale one — the checkout is main as it was at dispatch,
    so a run queued behind another (the workflow's concurrency group) does
    not have that run's line (35908375032 started behind 35907412563).
    Missing file and unparseable lines read as no history, never raise.
    """
    api = api or _api
    status, body = api(f"/api/evals/runs?repo={quote(repo, safe='')}&limit={PAST_RUNS_LIMIT}")
    runs = body.get("runs") if status == 200 and isinstance(body, dict) else None
    if isinstance(runs, list) and runs:
        return [r for r in runs if isinstance(r, dict)]
    return evals.read_history(history, repo)


def is_regression(previous: dict | None, current: dict) -> bool:
    """True only when a target flips from built to failed.

    A first-ever failure (no previous entry) and a repeat failure are both
    unsurprising — only a pass-then-fail transition is worth flagging. An
    already delivered run is neither side: it measured nothing, so it is
    never a regression and never the run a new one is compared with
    (`evals.last_measured`).
    """
    return (
        previous is not None
        and evals.outcome_of(previous) == evals.OUTCOME_BUILT
        and evals.outcome_of(current) == evals.OUTCOME_FAILED
    )


def annotate(level: str, message: str) -> None:
    """A line in the log, and an annotation on the run's summary page when
    the harness runs in GitHub Actions."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{level} title=E2E harness::{message}")


def run_one(repo: str, feature_text: str, feature: "evals.Feature | None",
            budget: int, history: pathlib.Path) -> tuple[bool, dict]:
    """One feature, one cycle, one scored line of history. True unless the
    run failed — an already delivered one is not a failure."""
    print(f"▶ {repo}: {feature_text.splitlines()[0][:70]}"
          + (f"  [{feature.id}]" if feature else ""))
    if not wait_for_health():
        sys.exit(f"FAIL start: {BASE}/health never answered 200 in {HEALTH_WAIT_SECONDS}s")
    seen = prs_before(repo)
    issue = create_issue(repo, feature_text)
    cycle_id = start_cycle(repo, issue)
    state, last_phase, cycle_id = wait_for(cycle_id, budget)

    new_prs = sorted(prs_before(repo) - seen)
    print(f"\n  cycle      : {state}" + (f" (last phase {last_phase})" if last_phase else ""))
    print(f"  pull req.  : {new_prs or 'none'}")

    ci: dict[int, str] = {}
    files: list[str] = []
    merged: list[int] = []
    for pr in new_prs:
        verdict = ci_verdict(_gh("pr", "checks", str(pr), "--repo", repo))
        ci[pr] = verdict
        files.extend(pr_files(repo, pr))
        # Not `state`: that name holds the *cycle* result the verdict below
        # depends on. Shadowing it made a passing run print
        # "FAIL — stopped at: MERGED" (cycle d4aad3415e99).
        pr_state = _gh("pr", "view", str(pr), "--repo", repo,
                       "--json", "state", "--jq", ".state")
        print(f"    #{pr}: {pr_state.lower()}, CI {verdict}, {len(pr_files(repo, pr))} file(s)")
        if pr_state.strip().upper() == "MERGED":
            merged.append(pr)

    left = unfinished_children(repo, issue)
    record = cycle_record(cycle_id)
    cycle_result = record.get("result") or {}
    satisfied = tuple(int(n) for n in cycle_result.get("already_satisfied") or ())
    if not new_prs:
        unexplained = sorted(set(closed_children(repo, issue)) - set(satisfied))
        if unexplained:
            print(f"  closed, not built: {', '.join(f'#{n}' for n in unexplained)}")
            left = sorted(set(left) | set(unexplained))
    if left:
        print(f"  unfinished : {', '.join(f'#{n}' for n in left)}")
    observed = evals.Observed(
        state=state,
        prs=tuple(new_prs),
        unfinished=tuple(left),
        ci=ci,
        files=tuple(files),
        review_decisions=tuple(review_decisions(cycle_result)),
        cost_usd=float(cycle_result.get("cost_usd") or 0.0),
        duration_s=duration_seconds(str(record.get("started_at") or ""), str(record.get("completed_at") or "")),
        backend=str(cycle_result.get("backend") or ""),
        tests_unavailable=bool(cycle_result.get("tests_unavailable")),
        already_satisfied=satisfied,
        merged=tuple(merged),
        qa=evals.qa_of(cycle_result.get("demo_report")),
    )
    result = {"repo": repo, **evals.score(feature, observed)}
    result["cycle_id"] = cycle_id
    result["issue"] = issue
    result["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    previous = evals.last_measured(past_runs(repo, history))
    result["regression"] = is_regression(previous, result)
    append_result(history, result)
    post_run(result)

    print(f"  cost/time  : ${result['cost_usd']:.2f} / {result['duration_s']}s"
          + (f"  (over budget)" if result["within_cost"] is False or result["within_time"] is False else "")
          + (f"  files {'ok' if result['files_match'] else 'off-target'}" if result["files_match"] is not None else ""))

    if result["passed"]:
        print("\nPASS — a feature was asked for, and the whole of it was built.")
        return True, result

    if result["outcome"] == evals.OUTCOME_ALREADY_DELIVERED:
        satisfied = ", ".join(f"#{n}" for n in result["already_satisfied"])
        message = (f"already delivered — the Dev found every sub-task on main "
                   f"({satisfied}); nothing was built, nothing measured")
        print(f"\nNOT MEASURED — {message}")
        annotate("warning", f"{repo}"
                 + (f" [{feature.id}]" if feature else "") + f": {message}")
        return True, result

    reasons = failure_reasons(state, new_prs=new_prs, left=left,
                              error=str(record.get("error") or ""))
    print("\nFAIL — " + "; ".join(reasons))
    if result["regression"]:
        print("\n⚠ REGRESSION — this target passed last run and fails now")
    summary = (
        f":red_circle: Harness failed on {repo}"
        + (f" [{feature.id}]" if feature else "")
        + f" — {'; '.join(reasons)}"
        + (" — REGRESSION" if result["regression"] else "")
        + f" (cycle {cycle_id}, issue #{issue})"
    )
    asyncio.run(alert_mattermost(summary))
    return False, result


def _known_feature(manifest, typed: str, feature_id: str = ""):
    """The manifest feature a typed `--feature` names, by id or exact text."""
    if manifest is None:
        return None
    if feature_id:
        return manifest.by_id(feature_id)
    wanted = typed.strip()
    by_id = manifest.by_id(wanted)
    if by_id is not None:
        return by_id
    return next((f for f in manifest.features if f.text.strip() == wanted), None)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--feature", default="", help="free text; empty = the eval manifest's feature of the day")
    ap.add_argument("--feature-id", default="", help="a feature id from the eval manifest")
    ap.add_argument("--all", action="store_true", help="run every feature of the manifest, in order")
    ap.add_argument("--budget", type=int, default=5400, help="seconds per cycle")
    ap.add_argument("--history", type=pathlib.Path,
                    default=pathlib.Path("docs/harness-runs.jsonl"))
    args = ap.parse_args()

    if not KEY:
        sys.exit("SWARM_ACCESS_KEY is unset")

    manifest = evals.manifest_for(args.repo)
    plan: list[tuple[str, "evals.Feature | None"]] = []
    if args.feature:
        # A manifest id ("venue-filter") or a manifest feature's exact text
        # runs as that feature, scored against its globs and budgets; any
        # other text runs unscored, as before. The workflow has one input.
        known = _known_feature(manifest, args.feature, args.feature_id)
        plan.append((known.text if known else args.feature, known))
    elif args.all:
        if manifest is None:
            sys.exit(f"no eval manifest for {args.repo} under {evals.EVALS_DIR}/")
        plan.extend((f.text, f) for f in manifest.features)
    elif args.feature_id:
        if manifest is None or manifest.by_id(args.feature_id) is None:
            sys.exit(f"unknown feature id {args.feature_id!r} for {args.repo}")
        feature = manifest.by_id(args.feature_id)
        plan.append((feature.text, feature))
    else:
        if manifest is None:
            sys.exit(f"no --feature given and no eval manifest for {args.repo}")
        history = past_runs(args.repo, args.history)
        if evals.exhausted(manifest, history):
            # A GitHub Actions annotation: it shows on the run's summary page.
            print(f"::warning::every feature of evals/{args.repo.split('/')[-1]}.yaml is "
                  f"already on {args.repo} — the run measures nothing new; add features")
        feature = evals.next_feature(manifest, history)
        of_the_day = evals.feature_of_the_day(manifest)
        if feature != of_the_day:
            print(f"  [{of_the_day.id}] is already on {args.repo} — running [{feature.id}] instead")
        plan.append((feature.text, feature))

    failures = 0
    for text, feature in plan:
        ok, _ = run_one(args.repo, text, feature, args.budget, args.history)
        failures += 0 if ok else 1
        if len(plan) > 1:
            print("\n" + "-" * 60 + "\n")
    if len(plan) > 1:
        print(f"{len(plan) - failures}/{len(plan)} features built")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
