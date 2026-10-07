"""What DevOps measures (D4): the CI's pace per job, the slot's cost, the cycle's price.

Read off the last runs of the deploy workflow on main — each job's
duration, its setup wait (the server-wide CI slot sits in GitHub's "Set
up runner" step), its failures — and off the harness's records (the
cost and length of a cycle). A measurement is never bad; it is a warning
when a job's setup wait costs more than the job itself.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

JOB_RUN_LIMIT = 8  # the completed runs whose jobs are read
SETUP_STEPS = ("Set up runner", "Set up job")  # where the runners' job-started hook (the slot) waits
SETUP_WARN_MINUTES = 5.0  # a median setup wait past this, and past the job's own work, is a warning
TOP_JOBS = 4  # the jobs named on the card, longest first


@dataclass(frozen=True)
class JobMeasure:
    name: str
    runs: int
    median_min: float  # the job's whole duration, setup included
    p90_min: float
    setup_min: float  # the median setup wait
    failures: int

    @property
    def work_min(self) -> float:
        return max(0.0, self.median_min - self.setup_min)

    @property
    def slot_dominates(self) -> bool:
        return self.setup_min >= SETUP_WARN_MINUTES and self.setup_min > self.work_min

    def as_dict(self) -> dict:
        return {"name": self.name, "runs": self.runs, "median_min": self.median_min, "p90_min": self.p90_min,
                "setup_min": self.setup_min, "failures": self.failures}


def _when(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _minutes(start: Any, end: Any) -> float | None:
    a, b = _when(start), _when(end)
    if a is None or b is None or b < a:
        return None
    return round((b - a).total_seconds() / 60, 2)


def job_dict(job, run_id: int | None = None) -> dict:
    """One PyGithub job as plain values: what `ci_measures` reads."""
    steps = []
    for step in getattr(job, "steps", None) or []:
        get = step.get if isinstance(step, dict) else lambda k, _s=step: getattr(_s, k, None)
        steps.append({"name": get("name") or "", "started_at": get("started_at"), "completed_at": get("completed_at")})
    return {
        "run_id": run_id if run_id is not None else getattr(job, "run_id", None), "name": getattr(job, "name", "") or "",
        "conclusion": getattr(job, "conclusion", None), "started_at": getattr(job, "started_at", None),
        "completed_at": getattr(job, "completed_at", None), "steps": steps,
    }


def _p90(values: list[float]) -> float:
    """Nearest-rank p90: the value nine tenths of the runs stay under."""
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.9 * len(ordered)) - 1)]


def ci_measures(jobs: list[dict]) -> list[JobMeasure]:
    """Per job name over the runs read: median and p90 duration, median setup wait, failures. Longest first."""
    by_name: dict[str, list[dict]] = {}
    for job in jobs:
        if job.get("name"):
            by_name.setdefault(str(job["name"]), []).append(job)
    out: list[JobMeasure] = []
    for name, rows in by_name.items():
        durations = [m for m in (_minutes(r.get("started_at"), r.get("completed_at")) for r in rows) if m is not None]
        if not durations:
            continue
        setups = []
        for r in rows:
            wait = sum(m or 0.0 for m in (_minutes(s.get("started_at"), s.get("completed_at"))
                                           for s in r.get("steps") or [] if s.get("name") in SETUP_STEPS))
            setups.append(round(wait, 2))
        out.append(JobMeasure(
            name=name, runs=len(rows), median_min=round(statistics.median(durations), 1), p90_min=round(_p90(durations), 1),
            setup_min=round(statistics.median(setups), 1) if setups else 0.0,
            failures=sum(1 for r in rows if r.get("conclusion") not in (None, "success", "skipped", "cancelled")),
        ))
    return sorted(out, key=lambda m: (-m.median_min, m.name))


def cycle_measure(records: list[dict]) -> dict | None:
    """The harness's cycles: median cost and length over the records that carry them."""
    costs = [float(r["cost_usd"]) for r in records if r.get("cost_usd") is not None]
    lengths = [float(r["duration_s"]) / 60 for r in records if r.get("duration_s")]
    if not costs and not lengths:
        return None
    return {"runs": max(len(costs), len(lengths)),
            "cost_usd": round(statistics.median(costs), 2) if costs else None,
            "duration_min": round(statistics.median(lengths), 1) if lengths else None}


def measures_facts(jobs: list[JobMeasure], cycle: dict | None) -> dict:
    return {"jobs": [j.as_dict() for j in jobs], "cycle": cycle}


def measures_finding(jobs: list[JobMeasure], cycle: dict | None):
    """The `measures` finding: the pace, read off the facts; a warning when the slot costs more than a job."""
    from theswarm.agents.devops import OK, UNKNOWN, WARN, Finding

    if not jobs and cycle is None:
        return Finding("measures", "CI pace", UNKNOWN, "no completed run of the deploy workflow on main to measure")
    words = []
    for j in jobs[:TOP_JOBS]:
        part = f"{j.name} {j.median_min:g} min median"
        extras = [f"p90 {j.p90_min:g}"] if j.p90_min > j.median_min else []
        if j.setup_min >= 1:
            extras.append(f"{j.setup_min:g} min of it setup wait")
        if j.failures:
            extras.append(f"{j.failures} of {j.runs} failed")
        words.append(part + (f" ({', '.join(extras)})" if extras else ""))
    runs = max((j.runs for j in jobs), default=0)
    detail = f"over {runs} runs: " + "; ".join(words) if words else "no job measured"
    if cycle:
        bits = []
        if cycle.get("cost_usd") is not None:
            bits.append(f"${cycle['cost_usd']:.2f}")
        if cycle.get("duration_min") is not None:
            bits.append(f"{cycle['duration_min']:g} min")
        if bits:
            detail += f" · a cycle costs {' and '.join(bits)} median over {cycle['runs']} runs"
    slow = [j for j in jobs if j.slot_dominates]
    if slow:
        names = ", ".join(j.name for j in slow)
        return Finding("measures", "CI pace", WARN, f"{detail} — the setup wait (the CI slot) costs more than the job itself on {names}")
    return Finding("measures", "CI pace", OK, detail)
