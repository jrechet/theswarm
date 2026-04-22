"""Value objects for the Scout bounded context (Phase G)."""

from __future__ import annotations

from enum import Enum


class IntelCategory(str, Enum):
    """How an intel item relates to our portfolio."""

    THREAT = "threat"  # competitor move, damaging change
    OPPORTUNITY = "opportunity"  # useful feature / library / idea
    CVE = "cve"  # security advisory on tracked dep
    FRAMEWORK = "framework"  # framework / language release
    PAPER = "paper"  # research paper / deep blog post
    FYI = "fyi"  # noteworthy but no action
    NOISE = "noise"  # false positive, ignore


class IntelUrgency(str, Enum):
    """How quickly a human should look at an item."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class SourceKind(str, Enum):
    """Kind of upstream feed / source."""

    RSS = "rss"
    GITHUB_TRENDING = "github_trending"
    GH_ADVISORY = "gh_advisory"
    HN = "hn"
    LOBSTERS = "lobsters"
    MASTODON = "mastodon"
    X = "x"
    CUSTOM = "custom"
