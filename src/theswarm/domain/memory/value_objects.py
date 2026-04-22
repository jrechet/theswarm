"""Value objects for the Memory bounded context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MemoryCategory(str, Enum):
    # Core (existing).
    STACK = "stack"
    CONVENTIONS = "conventions"
    ERRORS = "errors"
    ARCHITECTURE = "architecture"
    IMPROVEMENTS = "improvements"
    CROSS_PROJECT = "cross_project"
    # Role-specific categories introduced with Phase A / roster system.
    COMPETITORS = "competitors"
    POLICY = "policy"
    OKR = "okr"
    SIGNALS = "signals"
    DECISIONS = "decisions"
    ADRS = "adrs"
    DEBT = "debt"
    DEP_RADAR = "dep_radar"
    CRITICAL_PATHS = "critical_paths"
    REVIEW_CALIBRATION = "review_calibration"
    TEST_PATTERNS = "test_patterns"
    FLAKES = "flakes"
    GAPS = "gaps"
    PERF_BASELINES = "perf_baselines"
    A11Y_VIOLATIONS = "a11y_violations"
    TOKENS = "tokens"
    COMPONENTS = "components"
    REFERENCES = "references"
    RUNBOOKS = "runbooks"
    INCIDENTS = "incidents"
    ALERTS = "alerts"
    SLOS = "slos"
    INFRA_COSTS = "infra_costs"
    THREAT_MODEL = "threat_model"
    FINDINGS = "findings"
    AUTHZ = "authz"
    CRYPTO_INVENTORY = "crypto_inventory"
    METRICS = "metrics"
    EVENTS_SCHEMA = "events_schema"
    EXPERIMENTS = "experiments"
    COHORTS = "cohorts"
    STYLE_GUIDE = "style_guide"
    DOCS_MAP = "docs_map"
    TUTORIAL_INDEX = "tutorial_index"
    VERSIONS = "versions"
    ROLLOUTS = "rollouts"
    FLAGS = "flags"
    ROLLBACKS = "rollbacks"
    PAVED_ROAD = "paved_road"
    PORTFOLIO_ADRS = "portfolio_adrs"
    DIRECTION_BRIEFS = "direction_briefs"
    ROSTER = "roster"
    CADENCE = "cadence"
    BUDGETS = "budgets"
    HUMAN_PREFERENCES = "human_preferences"
    ESCALATIONS = "escalations"
    # Generic bucket for anything not yet modeled.
    LEARNINGS = "learnings"

    @classmethod
    def from_str(cls, value: str) -> MemoryCategory:
        """Tolerant parse; unknown values map to LEARNINGS."""
        if not value:
            return cls.LEARNINGS
        key = value.strip().lower().replace("-", "_").replace(" ", "_")
        try:
            return cls(key)
        except ValueError:
            return cls.LEARNINGS


class ScopeLayer(str, Enum):
    """Three-layer memory: global / project / role × project."""

    GLOBAL = "global"
    PROJECT = "project"
    ROLE_PROJECT = "role_project"


@dataclass(frozen=True)
class ProjectScope:
    """Scope of a memory entry: project-specific or global."""

    project_id: str = ""  # empty = global

    @property
    def is_global(self) -> bool:
        return not self.project_id

    def __str__(self) -> str:
        return self.project_id or "global"
