"""Value objects for the Architect bounded context (Phase K)."""

from __future__ import annotations

from enum import Enum


class RuleSeverity(str, Enum):
    """Strength of a paved-road rule."""

    ADVISORY = "advisory"  # nudge, don't block
    REQUIRED = "required"  # violation blocks merge / fails lint


class ADRStatus(str, Enum):
    """ADR lifecycle state (MADR-aligned)."""

    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


class BriefScope(str, Enum):
    """Whether a direction brief applies portfolio-wide or per-project."""

    PORTFOLIO = "portfolio"
    PROJECT = "project"
