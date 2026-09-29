#!/usr/bin/env python3
"""Put the stale `status:*` labels of a repository back in line with what
happened — the owner's "clean them all" (2026-09-29).

The board (V2, #257) shows an issue labelled in progress or in review that
nothing is working on as Stalled: on concert-tour-app, 39 of them, left by
cycles long gone. Each gets what its history says, never a blanket flip:

- a merged PR names it (`[#N]`, `Closes #N`) → closed, the PR cited;
- an open PR names it → `status:review` (it is in review);
- a story whose sub-tasks are all closed → closed;
- opened before `--close-before` → closed as not planned: the app has
  moved on since, and a ready `role:dev` task is what an untargeted Dev
  picks up next ("Set up FastAPI project structure", April) — reopening
  it asks for it again;
- anything else → back to `status:ready`, so Play picks it up again.

Every change carries a comment saying why. Dry run by default: the plan is
printed, nothing is written; `--apply` writes it. Never run it while a
cycle is working on the repository — its issues are legitimately in
progress.

    python scripts/clean_stale_labels.py --repo jrechet/concert-tour-app
    python scripts/clean_stale_labels.py --repo jrechet/concert-tour-app --apply
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass

STALE = ("status:in-progress", "status:review")
_TASK_RE = re.compile(r"\[#(\d+)\]|\bCloses #(\d+)", re.IGNORECASE)
_PARENT_RE = re.compile(r"^Parent: #(\d+)\b", re.MULTILINE)
MARKER = "<!-- swarm:label-cleanup -->"


@dataclass(frozen=True)
class Action:
    issue: int
    title: str
    kind: str  # "close" | "not_planned" | "review" | "ready"
    why: str
    remove: tuple[str, ...] = ()
    add: tuple[str, ...] = ()
    stale: tuple[str, ...] = ()  # the labels that were wrong


def _labels(issue: dict) -> set[str]:
    return {label if isinstance(label, str) else label.get("name", "") for label in issue.get("labels", [])}


def _named(prs: list[dict]) -> dict[int, int]:
    """Issue number → the PR that names it (the latest one)."""
    named: dict[int, int] = {}
    for pr in sorted(prs, key=lambda p: p["number"]):
        for pair in _TASK_RE.findall(f"{pr.get('title', '')}\n{pr.get('body') or ''}"):
            for n in pair:
                if n:
                    named[int(n)] = pr["number"]
    return named


def plan(open_issues: list[dict], closed_issues: list[dict],
         open_prs: list[dict], merged_prs: list[dict], close_before: str = "") -> list[Action]:
    """What to do with each stale issue — pure, for the tests and the dry run."""
    merged, in_review = _named(merged_prs), _named(open_prs)
    children: dict[int, list[int]] = {}
    for issue in open_issues + closed_issues:
        for parent in _PARENT_RE.findall(issue.get("body") or ""):
            children.setdefault(int(parent), []).append(issue["number"])
    closed = {i["number"] for i in closed_issues}

    actions: list[Action] = []
    for issue in sorted(open_issues, key=lambda i: i["number"]):
        labels = _labels(issue)
        stale = [label for label in STALE if label in labels]
        if not stale:
            continue
        number, title = issue["number"], issue.get("title", "")
        remove = tuple(label for label in labels if label.startswith("status:"))
        kids = children.get(number, [])
        was = tuple(stale)
        if number in merged:
            actions.append(Action(number, title, "close", f"merged in #{merged[number]}", stale=was))
        elif number in in_review:
            actions.append(Action(number, title, "review", f"#{in_review[number]} is open",
                                  tuple(r for r in remove if r != "status:review"), ("status:review",),
                                  stale=was))
        elif kids and all(k in closed for k in kids):
            actions.append(Action(number, title, "close",
                                  "every sub-task is closed: " + ", ".join(f"#{k}" for k in sorted(kids)),
                                  stale=was))
        elif close_before and (issue.get("created_at") or "9999") < close_before:
            actions.append(Action(number, title, "not_planned",
                                  f"opened {issue['created_at'][:10]}, before {close_before}, and the app has "
                                  "moved on since", stale=was))
        else:
            actions.append(Action(number, title, "ready", "no open PR and nothing is working on it",
                                  tuple(r for r in remove if r != "status:ready"), ("status:ready",),
                                  stale=was))
    return actions


def comment(action: Action, labels: tuple[str, ...] = ()) -> str:
    what = {"close": "Closing", "not_planned": "Closing as not planned (reopen it to ask again)",
            "review": "Back to `status:review`", "ready": "Back to `status:ready`"}[action.kind]
    was = ", ".join(f"`{label}`" for label in labels) or "a stale status"
    return (f"{what}: {action.why}. It was labelled {was} by a cycle long gone — "
            f"the swarm's board showed it as Stalled.\n\n{MARKER}")


def _gh(*args: str, input_text: str | None = None) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True,
                          input=input_text).stdout


def _all(repo: str, kind: str, state: str) -> list[dict]:
    out = _gh("api", "--paginate", f"repos/{repo}/{kind}?state={state}&per_page=100")
    items: list[dict] = []
    for chunk in re.split(r"(?<=\])\s*(?=\[)", out.strip()):
        if chunk:
            items.extend(json.loads(chunk))
    return items


def apply(repo: str, action: Action) -> None:
    _gh("api", f"repos/{repo}/issues/{action.issue}/comments", "-f",
        f"body={comment(action, action.stale)}")
    for label in action.remove:
        subprocess.run(["gh", "api", "-X", "DELETE",
                        f"repos/{repo}/issues/{action.issue}/labels/{label}"],
                       capture_output=True, text=True)
    if action.add:
        _gh("api", f"repos/{repo}/issues/{action.issue}/labels",
            *[arg for label in action.add for arg in ("-f", f"labels[]={label}")])
    if action.kind in ("close", "not_planned"):
        reason = "completed" if action.kind == "close" else "not_planned"
        _gh("api", "-X", "PATCH", f"repos/{repo}/issues/{action.issue}",
            "-f", "state=closed", "-f", f"state_reason={reason}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True)
    ap.add_argument("--apply", action="store_true", help="write the plan (default: print it)")
    ap.add_argument("--close-before", default="", help="YYYY-MM-DD: close older stale issues as not planned")
    ap.add_argument("--skip", type=int, nargs="*", default=[], help="issues a running cycle is working on")
    args = ap.parse_args()

    issues = [i for i in _all(args.repo, "issues", "all") if "pull_request" not in i]
    prs = _all(args.repo, "pulls", "all")
    actions = plan(
        [i for i in issues if i["state"] == "open"], [i for i in issues if i["state"] == "closed"],
        [p for p in prs if p["state"] == "open"], [p for p in prs if p.get("merged_at")],
        close_before=args.close_before,
    )
    actions = [a for a in actions if a.issue not in set(args.skip)]
    for a in actions:
        print(f"#{a.issue:<4} {a.kind:<6} {a.why:<46} {a.title[:60]}")
    counts = {k: sum(1 for a in actions if a.kind == k) for k in ("close", "not_planned", "review", "ready")}
    print(f"\n{len(actions)} stale: {counts}" + ("" if args.apply else "  (dry run — --apply to write)"))
    if args.apply:
        for a in actions:
            apply(args.repo, a)
            print(f"  done #{a.issue} → {a.kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
