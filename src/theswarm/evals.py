"""The eval suite: what the swarm is measured on, and how a run is scored.

V2 runtime, M6. The harness (`scripts/cycle_e2e.py`, run by
.github/workflows/harness.yml) used to ask one hard-coded feature and
answer pass or fail. Now it draws from a manifest (`evals/<target>.yaml`),
one feature a day in rotation (skipping the ones the target already has),
and scores what came out: the pull request, its CI, the reviews, cost,
duration, the files touched. Every run is a line in
docs/harness-runs.jsonl — the old fields kept, the new ones added — and
the repo page draws the trend from it.

Pure functions, no I/O beyond reading files: the harness and the web page
both use them, and tests cover them without a cycle.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml

EVALS_DIR = Path("evals")
HISTORY_PATH = Path("docs/harness-runs.jsonl")
TREND_WINDOW = 14  # runs shown on the repo page


@dataclass(frozen=True)
class Feature:
    id: str
    text: str
    expected_paths: tuple[str, ...] = ()
    max_cost_usd: float = 0.0
    max_duration_s: int = 0

    @property
    def title(self) -> str:
        return self.text.splitlines()[0].strip()


@dataclass(frozen=True)
class Manifest:
    repo: str
    features: tuple[Feature, ...] = ()

    def by_id(self, feature_id: str) -> Feature | None:
        return next((f for f in self.features if f.id == feature_id), None)


def load_manifest(path: Path) -> Manifest:
    raw = yaml.safe_load(Path(path).read_text()) or {}
    features = tuple(
        Feature(
            id=str(entry["id"]),
            text=str(entry["text"]).strip(),
            expected_paths=tuple(entry.get("expected_paths") or ()),
            max_cost_usd=float(entry.get("max_cost_usd") or 0.0),
            max_duration_s=int(entry.get("max_duration_s") or 0),
        )
        for entry in raw.get("features") or []
    )
    if not features:
        raise ValueError(f"{path}: no features")
    return Manifest(repo=str(raw.get("repo", "")), features=features)


def manifest_for(repo: str, evals_dir: Path = EVALS_DIR) -> Manifest | None:
    """The manifest whose `repo` matches, or None — a repo without one runs
    the harness the old way, with the feature it was given."""
    for path in sorted(Path(evals_dir).glob("*.yaml")):
        try:
            manifest = load_manifest(path)
        except (OSError, ValueError, KeyError):
            continue
        if manifest.repo == repo:
            return manifest
    return None


def _day_index(manifest: Manifest, day: date | None) -> int:
    day = day or datetime.now(timezone.utc).date()
    return day.timetuple().tm_yday % len(manifest.features)


def feature_of_the_day(manifest: Manifest, day: date | None = None) -> Feature:
    """Rotation by day of year: every feature comes around, one a day."""
    return manifest.features[_day_index(manifest, day)]


def delivered_features(runs: list[dict]) -> set[str]:
    """Feature ids whose latest run built them or found them built.

    The latest run decides: a feature that failed since (a target reset, a
    regression) is worth running again.
    """
    latest: dict[str, str] = {}
    for run in runs:
        if run.get("feature"):
            latest[str(run["feature"])] = outcome_of(run)
    return {fid for fid, outcome in latest.items() if outcome in DELIVERED}


def next_feature(manifest: Manifest, runs: list[dict], day: date | None = None) -> Feature:
    """The feature of the day, unless the target already has it — then the
    next one in rotation it does not have.

    The rotation alone gave every dispatch of a day the same feature: on
    2026-09-23 the fourth run asked for the city search two runs had
    already merged, the Dev rightly closed each sub-task as already
    satisfied, and the harness reported a regression (cycle 874f575645f2).
    When every feature is delivered, the feature of the day runs anyway
    and its score says so.
    """
    start = _day_index(manifest, day)
    delivered = delivered_features(runs)
    count = len(manifest.features)
    for offset in range(count):
        feature = manifest.features[(start + offset) % count]
        if feature.id not in delivered:
            return feature
    return manifest.features[start]


def exhausted(manifest: Manifest, runs: list[dict]) -> bool:
    """True when the target already has every feature of the manifest.

    The rotation then runs a delivered feature, which scores
    already_delivered and measures nothing new: the manifest needs new
    features. The first five were all built by 2026-09-25.
    """
    delivered = delivered_features(runs)
    return all(feature.id in delivered for feature in manifest.features)


QA_GATES = ("unit_tests", "e2e_tests", "security", "coverage")


def qa_of(demo_report: dict | None) -> dict[str, str]:
    """Gate → status from a cycle's demo report; {} when there is none."""
    gates = (demo_report or {}).get("quality_gates") or {}
    return {
        gate: str(gates[gate].get("status"))
        for gate in QA_GATES
        if isinstance(gates.get(gate), dict) and gates[gate].get("status")
    }


# ── Scoring ──────────────────────────────────────────────────────────

# What a run says about the swarm. `already_delivered` measured nothing:
# the cycle ran, and every sub-task was already on main — neither a pass
# nor a failure, and never a regression.
OUTCOME_BUILT = "built"
OUTCOME_FAILED = "failed"
OUTCOME_ALREADY_DELIVERED = "already_delivered"
DELIVERED = frozenset({OUTCOME_BUILT, OUTCOME_ALREADY_DELIVERED})


@dataclass(frozen=True)
class Observed:
    """What the harness saw once the cycle ended."""

    state: str
    prs: tuple[int, ...] = ()
    unfinished: tuple[int, ...] = ()
    ci: dict[int, str] = field(default_factory=dict)  # pr → "green" | "RED" | "none"
    files: tuple[str, ...] = ()
    review_decisions: tuple[str, ...] = ()
    cost_usd: float = 0.0
    duration_s: float = 0.0
    backend: str = ""
    tests_unavailable: bool = False
    already_satisfied: tuple[int, ...] = ()  # sub-tasks the Dev closed as already built
    # What GitHub says is merged once the cycle ended. A PR can be approved
    # and still sit open: cycle 9d3174f41829's #325 conflicted with its
    # sibling and never merged, under a run scored "built".
    merged: tuple[int, ...] = ()
    # QA's gates as the cycle's demo report states them: gate → status
    # ("pass" | "fail" | "not_run"). The E2E run of 9d3174f41829 ended in 24
    # errors and no eval record said so.
    qa: dict[str, str] = field(default_factory=dict)


def outcome_of(run: dict) -> str:
    """A record's outcome; records from before the field read off `passed`."""
    outcome = run.get("outcome")
    if outcome in (OUTCOME_BUILT, OUTCOME_FAILED, OUTCOME_ALREADY_DELIVERED):
        return str(outcome)
    return OUTCOME_BUILT if run.get("passed") else OUTCOME_FAILED


def is_measured(run: dict) -> bool:
    return outcome_of(run) != OUTCOME_ALREADY_DELIVERED


def files_match(files: tuple[str, ...] | list[str], expected: tuple[str, ...]) -> bool | None:
    """None when nothing is expected (not judged); else every file matches
    some glob — the PR stayed where the feature lives."""
    if not expected:
        return None
    if not files:
        return False
    return all(any(fnmatch.fnmatch(f, pattern) for pattern in expected) for f in files)


def score(feature: Feature | None, observed: Observed) -> dict[str, Any]:
    """The run record. `passed` keeps its meaning from before M6 — the
    cycle completed, a PR came out, no sub-task was left unbuilt — so the
    history stays comparable; the budgets and the file check are their own
    fields, judged on the page.

    A completed cycle with no PR and nothing left open, whose Dev closed
    its sub-tasks as already satisfied, is `already_delivered`: `passed`
    stays False (no PR came out) and `outcome` says why.
    """
    finished = observed.state == "completed" and not observed.unfinished
    passed = finished and bool(observed.prs)
    if passed:
        outcome = OUTCOME_BUILT
    elif finished and not observed.prs and observed.already_satisfied:
        outcome = OUTCOME_ALREADY_DELIVERED
    else:
        outcome = OUTCOME_FAILED
    within_cost = (
        None if not feature or not feature.max_cost_usd
        else observed.cost_usd <= feature.max_cost_usd
    )
    within_time = (
        None if not feature or not feature.max_duration_s
        else observed.duration_s <= feature.max_duration_s
    )
    ci_values = list(observed.ci.values())
    ci = "RED" if "RED" in ci_values else ("green" if "green" in ci_values else "none")
    return {
        "passed": passed,
        "outcome": outcome,
        "state": observed.state,
        "prs": list(observed.prs),
        "merged": list(observed.merged),
        "unmerged": [pr for pr in observed.prs if pr not in set(observed.merged)],
        "qa": dict(observed.qa),
        "unfinished": list(observed.unfinished),
        "already_satisfied": list(observed.already_satisfied),
        "feature": feature.id if feature else "",
        "ci": ci,
        "review_decisions": list(observed.review_decisions),
        "cost_usd": round(float(observed.cost_usd), 4),
        "duration_s": int(observed.duration_s),
        "within_cost": within_cost,
        "within_time": within_time,
        # Nothing was written: there are no files to judge, not wrong ones.
        "files_match": (
            None if outcome == OUTCOME_ALREADY_DELIVERED
            else files_match(observed.files, feature.expected_paths if feature else ())
        ),
        "backend": observed.backend,
        "tests_unavailable": observed.tests_unavailable,
    }


# ── History ──────────────────────────────────────────────────────────


def read_history(path: Path = HISTORY_PATH, repo: str | None = None) -> list[dict]:
    """Every parseable line, oldest first; unparseable lines are skipped."""
    if not Path(path).exists():
        return []
    entries: list[dict] = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if repo is None or entry.get("repo") == repo:
            entries.append(entry)
    return entries


def last_measured(entries: list[dict]) -> dict | None:
    """The most recent run that measured something — what a new run is
    compared with to call a regression."""
    return next((e for e in reversed(entries) if is_measured(e)), None)


def trend(entries: list[dict], window: int = TREND_WINDOW) -> dict[str, Any]:
    """The last `window` runs, summarised for the page. The pass rate and
    the per-backend counts are over measured runs only; an already
    delivered run is drawn, not counted."""
    recent = entries[-window:]
    if not recent:
        return {"runs": [], "count": 0, "pass_rate": None, "avg_cost_usd": None,
                "avg_duration_s": None, "by_backend": {}, "already_delivered": 0,
                "left_open": 0, "qa_red": 0, "last": None}
    measured = [e for e in recent if is_measured(e)]
    passed = sum(1 for e in measured if e.get("passed"))
    costs = [float(e["cost_usd"]) for e in recent if e.get("cost_usd") is not None]
    durations = [float(e["duration_s"]) for e in recent if e.get("duration_s")]
    by_backend: dict[str, dict[str, int]] = {}
    for e in measured:
        bucket = by_backend.setdefault(e.get("backend") or "unknown", {"runs": 0, "passed": 0})
        bucket["runs"] += 1
        bucket["passed"] += 1 if e.get("passed") else 0
    return {
        "runs": recent,
        "count": len(recent),
        "pass_rate": (passed / len(measured)) if measured else None,
        "avg_cost_usd": (sum(costs) / len(costs)) if costs else None,
        "avg_duration_s": (sum(durations) / len(durations)) if durations else None,
        "by_backend": by_backend,
        "already_delivered": len(recent) - len(measured),
        # Built runs whose PRs did not all merge (records before the field
        # carry no `unmerged` and count as nothing left open).
        "left_open": sum(1 for e in measured if e.get("unmerged")),
        # Runs where a QA gate failed (records before the field: none).
        "qa_red": sum(1 for e in recent if "fail" in (e.get("qa") or {}).values()),
        "last": recent[-1],
    }
