"""The eval suite: what the swarm is measured on, and how a run is scored.

V2 runtime, M6. The harness (`scripts/cycle_e2e.py`, run by
.github/workflows/harness.yml) used to ask one hard-coded feature and
answer pass or fail. Now it draws from a manifest (`evals/<target>.yaml`),
one feature a day in rotation, and scores what came out: the pull request,
its CI, the reviews, cost, duration, the files touched. Every run is a
line in docs/harness-runs.jsonl — the old fields kept, the new ones added
— and the repo page draws the trend from it.

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


def feature_of_the_day(manifest: Manifest, day: date | None = None) -> Feature:
    """Rotation by day of year: every feature comes around, one a day."""
    day = day or datetime.now(timezone.utc).date()
    return manifest.features[day.timetuple().tm_yday % len(manifest.features)]


# ── Scoring ──────────────────────────────────────────────────────────


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
    fields, judged on the page."""
    passed = observed.state == "completed" and bool(observed.prs) and not observed.unfinished
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
        "state": observed.state,
        "prs": list(observed.prs),
        "unfinished": list(observed.unfinished),
        "feature": feature.id if feature else "",
        "ci": ci,
        "review_decisions": list(observed.review_decisions),
        "cost_usd": round(float(observed.cost_usd), 4),
        "duration_s": int(observed.duration_s),
        "within_cost": within_cost,
        "within_time": within_time,
        "files_match": files_match(observed.files, feature.expected_paths if feature else ()),
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


def trend(entries: list[dict], window: int = TREND_WINDOW) -> dict[str, Any]:
    """The last `window` runs, summarised for the page."""
    recent = entries[-window:]
    if not recent:
        return {"runs": [], "count": 0, "pass_rate": None, "avg_cost_usd": None,
                "avg_duration_s": None, "by_backend": {}, "last": None}
    passed = sum(1 for e in recent if e.get("passed"))
    costs = [float(e["cost_usd"]) for e in recent if e.get("cost_usd") is not None]
    durations = [float(e["duration_s"]) for e in recent if e.get("duration_s")]
    by_backend: dict[str, dict[str, int]] = {}
    for e in recent:
        bucket = by_backend.setdefault(e.get("backend") or "unknown", {"runs": 0, "passed": 0})
        bucket["runs"] += 1
        bucket["passed"] += 1 if e.get("passed") else 0
    return {
        "runs": recent,
        "count": len(recent),
        "pass_rate": passed / len(recent),
        "avg_cost_usd": (sum(costs) / len(costs)) if costs else None,
        "avg_duration_s": (sum(durations) / len(durations)) if durations else None,
        "by_backend": by_backend,
        "last": recent[-1],
    }
