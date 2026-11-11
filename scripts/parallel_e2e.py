#!/usr/bin/env python3
"""Ask for several features at once and judge what one run alone cannot.

`cycle_e2e.py` proves the swarm builds a feature. This proves it builds
several at the same time — on different repositories, or side by side on
one — without one cycle stepping on another:

    scripts/parallel_e2e.py \
        --ask "jrechet/concert-tour-app: List a venue's concerts …" \
        --ask "jrechet/concert-tour-app: Count the concerts per artist …" \
        --ask "jrechet/swarm-todo-app: Delete a todo …"

Every ask becomes an issue and a cycle pinned to it, all started within
seconds. While they run the script samples each cycle (queued, running,
which phase) and afterwards reads GitHub. Beyond what the single harness
checks (finished, a pull request, no sub-task left open) it judges the
batch:

- **ownership** — every pull request a cycle opened names a sub-task of
  that cycle's own feature, never a sibling's;
- **no double build** — no sub-task carries pull requests from two cycles;
- **the gate** — never more cycles running at once than `--limit` allows;
- **nobody starves** — every cycle of the batch ran.

Exit code 0 when the batch has no problem. The timeline printed at the end
(waited, ran, cost) is the measure of what running in parallel buys.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import cycle_e2e as harness  # noqa: E402 — the single-run harness's helpers

POLL_SECONDS = 15
_TASK_IN_TITLE = re.compile(r"^\s*\[#(\d+)\]")
_TASK_IN_BRANCH = re.compile(r"issue-(\d+)(?!\d)")


def parse_ask(arg: str) -> tuple[str, str]:
    """`owner/name: the feature, as the composer takes it` → (repo, text)."""
    repo, sep, text = arg.partition(":")
    repo, text = repo.strip(), text.strip()
    if not sep or repo.count("/") != 1 or not text:
        raise ValueError(f"an ask is 'owner/name: feature text', got {arg!r}")
    return repo, text


def task_of(pr: dict) -> int | None:
    """The sub-task a Dev pull request builds: `[#N]` in its title, else `issue-N` in its branch."""
    found = _TASK_IN_TITLE.search(str(pr.get("title") or "")) or _TASK_IN_BRANCH.search(str(pr.get("headRefName") or ""))
    return int(found.group(1)) if found else None


def phase_of(body: dict) -> str:
    """The phase a cycle is in, off its row: the last phase still running, else the last announced."""
    phases = [p for p in body.get("phases") or [] if isinstance(p, dict)]
    running = [p for p in phases if p.get("status") == "running"]
    last = (running or phases or [{}])[-1]
    return str(last.get("phase") or body.get("current_phase") or "")


def most_at_once(samples: list[dict[str, str]]) -> int:
    """The most cycles seen `running` in one sample."""
    return max((sum(1 for state in sample.values() if state == "running") for sample in samples), default=0)


def judge(runs: list[dict], samples: list[dict[str, str]] | None = None, limit: int = 0) -> list[str]:
    """What went wrong in a batch, in words; empty when nothing did.

    A run is a plain dict: `repo`, `story`, `cycle`, `state`, `error`,
    `opened` (the pull requests its cycle reports), `pr_tasks` ({pr: the
    sub-task it names}), `children` (its feature's sub-tasks), `open_children`
    (those still open and not in review), `already_satisfied`.
    """
    problems: list[str] = []
    owner_of_task = {(r["repo"], task): r for r in runs for task in r.get("children", [])}
    built_by: dict[tuple[str, int], list[str]] = {}
    for r in runs:
        name = f"cycle {r.get('cycle') or '?'} ({r['repo']}#{r['story']})"
        if r.get("state") != "completed":
            problems.append(f"{name} ended {r.get('state') or 'unknown'}" + (f": {str(r['error'])[:160]}" if r.get("error") else ""))
            if not r.get("ran"):
                problems.append(f"{name} never ran")
            continue
        if r.get("open_children"):
            problems.append(f"{name} left sub-tasks open: {', '.join(f'#{n}' for n in r['open_children'])}")
        if not r.get("opened") and not r.get("already_satisfied"):
            problems.append(f"{name} built nothing: no pull request, no sub-task found already on main")
        for pr in r.get("opened", []):
            task = (r.get("pr_tasks") or {}).get(pr)
            if task is None:
                continue
            built_by.setdefault((r["repo"], task), []).append(str(r.get("cycle")))
            owner = owner_of_task.get((r["repo"], task))
            if owner is not None and owner is not r:
                problems.append(f"{name} opened PR #{pr} for #{task}, a sub-task of #{owner['story']} — "
                                f"cycle {owner.get('cycle')}'s feature")
    for (repo, task), cycles in sorted(built_by.items()):
        if len(set(cycles)) > 1:
            problems.append(f"{repo}#{task} was built by {len(set(cycles))} cycles: {', '.join(sorted(set(cycles)))}")
    seen = most_at_once(samples or [])
    if limit and seen > limit:
        problems.append(f"{seen} cycles ran at once, the limit is {limit}")
    return problems


# ── Reading GitHub and the service ───────────────────────────────────


def children_of(repo: str, story: int) -> tuple[list[int], list[int]]:
    """(every sub-task of the story, those still open and not in review)."""
    raw = harness._gh("issue", "list", "--repo", repo, "--state", "all", "--limit", "100", "--json", "number,body,state,labels")
    mine = [i for i in json.loads(raw or "[]") if harness._child_of(i.get("body"), story)]
    still_open = [i["number"] for i in mine if str(i.get("state", "")).upper() == "OPEN"
                  and "status:review" not in {label["name"] for label in i.get("labels", [])}]
    return sorted(i["number"] for i in mine), sorted(still_open)


def tasks_of_prs(repo: str, prs: list[int]) -> dict[int, int | None]:
    if not prs:
        return {}
    raw = harness._gh("pr", "list", "--repo", repo, "--state", "all", "--limit", "100", "--json", "number,title,headRefName")
    by_number = {p["number"]: p for p in json.loads(raw or "[]")}
    return {n: task_of(by_number.get(n, {})) for n in prs}


def watch(runs: list[dict], budget_s: int, *, api=None, sleep=time.sleep, clock=time.time) -> list[dict[str, str]]:
    """Poll every cycle until all are terminal; each run gains `state`, `timeline`, `ran`, `record`."""
    api = api or harness._api
    started = clock()
    samples: list[dict[str, str]] = []
    for r in runs:
        r.update(state="", timeline=[], ran=False, hops=0)
    while clock() - started < budget_s:
        sample: dict[str, str] = {}
        for r in runs:
            if r["state"] in harness.TERMINAL:
                continue
            status, body = api(f"/api/cycles/{r['cycle']}")
            if status != 200:
                continue  # a rolling deploy answers 404 for a while; the next poll asks again
            state, phase = str(body.get("status") or ""), phase_of(body)
            if state in harness.TERMINAL and body.get("resumed_as") and r["hops"] < harness.MAX_RESUME_HOPS:
                r["timeline"].append((round(clock() - started), "resumed", str(body["resumed_as"])))
                r.update(cycle=str(body["resumed_as"]), hops=r["hops"] + 1)
                continue
            if not r["timeline"] or r["timeline"][-1][1:] != (state, phase):
                r["timeline"].append((round(clock() - started), state, phase))
                print(f"  [{time.strftime('%H:%M:%S')}] {r['repo'].split('/')[-1]}#{r['story']} {r['cycle']}: {state}"
                      + (f" ({phase})" if phase else ""), flush=True)
            r["ran"] = r["ran"] or state == "running" or (state == "completed")
            r.update(state=state if state in harness.TERMINAL else "", record=body)
            sample[r["cycle"]] = state
        if sample:
            samples.append(sample)
        if all(r["state"] in harness.TERMINAL for r in runs):
            return samples
        sleep(POLL_SECONDS)
    for r in runs:
        r["state"] = r["state"] or "timeout"
    return samples


def spans(timeline: list[tuple[int, str, str]]) -> tuple[int, int]:
    """(seconds waited before running, seconds from the first `running` to the end)."""
    first_run = next((t for t, state, _ in timeline if state == "running"), None)
    end = timeline[-1][0] if timeline else 0
    if first_run is None:
        return end, 0
    return first_run, end - first_run


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ask", action="append", required=True, help="'owner/name: feature text' — repeat for each feature")
    ap.add_argument("--limit", type=int, default=0, help="the instance's 'in all' bound; 0 = not judged")
    ap.add_argument("--budget", type=int, default=7200, help="seconds for the whole batch")
    ap.add_argument("--out", type=pathlib.Path, default=None, help="write the batch as JSON here")
    args = ap.parse_args()
    asks = [parse_ask(a) for a in args.ask]

    if not harness.wait_for_health():
        sys.exit(f"FAIL start: {harness.BASE}/health never answered 200")
    answer = harness.claude_answer()
    if answer and answer.get("claude") != "ok":
        wall = answer.get("claude_quota_resets_at") or answer.get("claude_auth") or answer.get("detail") or ""
        print(f"NOT MEASURED — Claude does not answer ({answer['claude']}{': ' + str(wall) if wall else ''}); "
              "no issue created, no cycle started")
        return 0

    print(f"Starting {len(asks)} features at once on {harness.BASE}")
    runs: list[dict] = []
    before = {repo: harness.prs_before(repo) for repo in {repo for repo, _ in asks}}
    for repo, text in asks:
        runs.append({"repo": repo, "text": text, "story": harness.create_issue(repo, text)})
    for r in runs:
        r["cycle"] = r["first_cycle"] = harness.start_cycle(r["repo"], r["story"])

    samples = watch(runs, args.budget)

    for r in runs:
        record = r.get("record") or {}
        result = record.get("result") or {}
        r["error"] = record.get("error") or ""
        r["opened"] = sorted(set(record.get("prs_opened") or []))
        r["merged"] = sorted(set(record.get("prs_merged") or []))
        r["already_satisfied"] = list(result.get("already_satisfied") or [])
        r["cost_usd"] = harness.cycle_cost(record)
        r["children"], r["open_children"] = children_of(r["repo"], r["story"])
        r["pr_tasks"] = tasks_of_prs(r["repo"], r["opened"])
    unowned = {repo: sorted(harness.prs_before(repo) - seen - {pr for r in runs if r["repo"] == repo for pr in r["opened"]})
               for repo, seen in before.items()}

    problems = judge(runs, samples, args.limit)
    problems += [f"{repo}: pull request(s) {', '.join(f'#{n}' for n in prs)} appeared during the batch and no cycle reports them"
                 for repo, prs in sorted(unowned.items()) if prs]

    print("\n" + "=" * 72)
    for r in runs:
        waited, ran = spans(r["timeline"])
        print(f"{r['repo']}#{r['story']}  cycle {r['cycle']}  {r['state']}  waited {waited // 60} min, ran {ran // 60} min, "
              f"${r['cost_usd']:.2f}  PRs {r['opened']} merged {r['merged']}  sub-tasks {r['children']}")
    print(f"most cycles running at once: {most_at_once(samples)}" + (f" (limit {args.limit})" if args.limit else ""))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({"runs": [{k: v for k, v in r.items() if k != "record"} for r in runs],
                                        "most_at_once": most_at_once(samples), "problems": problems}, indent=2, default=str))
    if problems:
        print("\nFAIL — the batch has problems:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"\nPASS — {len(runs)} features built at once, each cycle on its own work")
    return 0


if __name__ == "__main__":
    sys.exit(main())
