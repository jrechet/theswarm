"""Entities for the QA-enrichments bounded context (Phase F)."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from theswarm.domain.qa.value_objects import (
    GateName,
    GateStatus,
    QuarantineStatus,
    TestArchetype,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _rand(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


@dataclass(frozen=True)
class TestPlan:
    """Per-story/task plan of required test archetypes vs. what was produced."""

    __test__ = False  # pytest: not a test class

    id: str
    project_id: str
    task_id: str
    required: tuple[TestArchetype, ...] = ()
    produced: tuple[TestArchetype, ...] = ()
    notes: str = ""
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("plan")

    @property
    def missing(self) -> tuple[TestArchetype, ...]:
        produced_set = set(self.produced)
        return tuple(a for a in self.required if a not in produced_set)

    @property
    def satisfied(self) -> bool:
        return len(self.missing) == 0

    @property
    def coverage_ratio(self) -> float:
        if not self.required:
            return 1.0
        covered = sum(1 for a in self.required if a in set(self.produced))
        return round(covered / len(self.required), 3)


@dataclass(frozen=True)
class FlakeRecord:
    """Running count of runs vs. failures for a single test identifier."""

    id: str
    project_id: str
    test_id: str  # e.g. "tests/e2e/login.py::test_login"
    runs: int = 0
    failures: int = 0
    last_failure_reason: str = ""
    last_run_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("flake")

    @property
    def flake_score(self) -> float:
        """Failures ÷ runs, clamped to [0, 1]."""
        if self.runs <= 0:
            return 0.0
        return round(min(1.0, self.failures / self.runs), 3)

    def should_quarantine(self, *, threshold: float = 0.2, min_runs: int = 5) -> bool:
        """True once we've seen enough runs and the flake score is too high."""
        return self.runs >= min_runs and self.flake_score >= threshold


@dataclass(frozen=True)
class QuarantineEntry:
    """A test removed from the blocking suite pending investigation."""

    id: str
    project_id: str
    test_id: str
    reason: str = ""
    status: QuarantineStatus = QuarantineStatus.ACTIVE
    quarantined_at: datetime = field(default_factory=_now)
    released_at: datetime | None = None
    released_reason: str = ""

    @staticmethod
    def new_id() -> str:
        return _rand("quar")


@dataclass(frozen=True)
class QualityGate:
    """A named quality gate result captured against a project (optionally PR)."""

    id: str
    project_id: str
    gate: GateName
    status: GateStatus = GateStatus.UNKNOWN
    summary: str = ""
    pr_url: str = ""
    task_id: str = ""
    score: float | None = None  # numeric result (perf score, RPS, etc.)
    finding_count: int = 0  # relevant counts (violations, vulns)
    details_json: str = "{}"  # opaque per-gate payload
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("gate")

    @property
    def is_blocking(self) -> bool:
        """A gate blocks only when it explicitly failed."""
        return self.status == GateStatus.FAIL


@dataclass(frozen=True)
class StoryAcceptance:
    """A single acceptance-criterion line for a story outcome card."""

    text: str
    passed: bool = False
    evidence: str = ""  # optional short pointer (screenshot path, assertion)


@dataclass(frozen=True)
class OutcomeCard:
    """One-slide demo artifact: acceptance criteria + metric delta for a story."""

    id: str
    project_id: str
    story_id: str = ""
    title: str = ""
    acceptance: tuple[StoryAcceptance, ...] = ()
    metric_name: str = ""
    metric_before: str = ""
    metric_after: str = ""
    screenshot_path: str = ""
    narrated_video_path: str = ""
    summary: str = ""
    created_at: datetime = field(default_factory=_now)

    @staticmethod
    def new_id() -> str:
        return _rand("card")

    @property
    def pass_count(self) -> int:
        return sum(1 for a in self.acceptance if a.passed)

    @property
    def fail_count(self) -> int:
        return sum(1 for a in self.acceptance if not a.passed)

    @property
    def all_passed(self) -> bool:
        return bool(self.acceptance) and self.fail_count == 0
