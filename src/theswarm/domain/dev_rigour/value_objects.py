"""Value objects for the Dev-rigour bounded context."""

from __future__ import annotations

from enum import Enum


class ThoughtKind(str, Enum):
    """Kind of dev exploration/research step logged to the thoughts stream."""

    EXPLORE = "explore"  # grep/glob of the area
    REUSE = "reuse"  # search for existing utility
    LIBRARY = "library"  # docs-lookup / Context7
    PLAN = "plan"  # short written plan before editing
    NOTE = "note"  # free-form note


class TddPhase(str, Enum):
    """Phase of the TDD gate for a given task."""

    RED = "red"  # failing test recorded
    GREEN = "green"  # implementation passes tests
    REFACTOR = "refactor"  # post-green cleanup


class PreflightDecision(str, Enum):
    """Outcome of a refactor preflight check."""

    PROCEED = "proceed"
    BAIL = "bail"


class FindingSeverity(str, Enum):
    """Severity of a self-review finding."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
