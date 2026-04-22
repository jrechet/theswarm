"""Value objects for the QA-enrichments bounded context."""

from __future__ import annotations

from enum import Enum


class TestArchetype(str, Enum):
    """Kind of test required or produced for a given story/task."""

    __test__ = False  # pytest: not a test class

    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"
    VISUAL = "visual"
    A11Y = "a11y"
    PERF = "perf"
    SECURITY = "security"


class GateName(str, Enum):
    """Named quality gate captured on a cycle or PR."""

    AXE = "axe"  # accessibility
    LIGHTHOUSE = "lighthouse"  # perf
    K6 = "k6"  # API load smoke
    GITLEAKS = "gitleaks"  # secret scan
    OSV = "osv"  # SCA
    SBOM = "sbom"  # software bill of materials
    LICENSE = "license"  # license audit


class GateStatus(str, Enum):
    """Result of running a quality gate."""

    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    SKIPPED = "skipped"
    UNKNOWN = "unknown"


class QuarantineStatus(str, Enum):
    """State of a quarantined test."""

    ACTIVE = "active"  # currently quarantined
    RELEASED = "released"  # back in rotation
