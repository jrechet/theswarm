"""Value objects for the Analyst bounded context (Phase J)."""

from __future__ import annotations

from enum import Enum


class MetricKind(str, Enum):
    """How a metric is measured."""

    COUNTER = "counter"  # cumulative count (events, errors)
    GAUGE = "gauge"  # point-in-time value (memory, active users)
    HISTOGRAM = "histogram"  # distribution (latency buckets)
    RATIO = "ratio"  # conversion, hit rate, error rate
    CURRENCY = "currency"  # revenue, cost


class InstrumentationStatus(str, Enum):
    """Lifecycle of a per-story instrumentation plan."""

    PROPOSED = "proposed"
    IMPLEMENTED = "implemented"
    VERIFIED = "verified"
    MISSING = "missing"  # flagged because story shipped without it


class OutcomeDirection(str, Enum):
    """Whether the metric moved as expected."""

    IMPROVED = "improved"  # moved in the expected direction
    UNCHANGED = "unchanged"  # no significant move
    REGRESSED = "regressed"  # moved wrong direction
    INCONCLUSIVE = "inconclusive"  # not enough data
