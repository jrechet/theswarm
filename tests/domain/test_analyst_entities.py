"""Phase J domain tests — Analyst entities."""

from __future__ import annotations

from theswarm.domain.analyst.entities import (
    InstrumentationPlan,
    MetricDefinition,
    OutcomeObservation,
)
from theswarm.domain.analyst.value_objects import (
    InstrumentationStatus,
    MetricKind,
    OutcomeDirection,
)


class TestMetricDefinition:
    def test_defaults(self):
        m = MetricDefinition(
            id="m1", project_id="p", name="signup_conversion",
            kind=MetricKind.RATIO, unit="%",
            definition="signups / visitors",
        )
        assert m.unit == "%"
        assert m.kind == MetricKind.RATIO
        assert m.target == ""


class TestInstrumentationPlan:
    def test_missing_is_blocking(self):
        p = InstrumentationPlan(
            id="p1", project_id="p", story_id="S1",
            metric_name="signup_conversion",
            status=InstrumentationStatus.MISSING,
        )
        assert p.is_blocking_outcome

    def test_verified_is_not_blocking(self):
        p = InstrumentationPlan(
            id="p1", project_id="p", story_id="S1",
            metric_name="signup_conversion",
            status=InstrumentationStatus.VERIFIED,
        )
        assert not p.is_blocking_outcome


class TestOutcomeObservation:
    def test_improved_is_positive(self):
        o = OutcomeObservation(
            id="o1", project_id="p", story_id="S1",
            metric_name="signup_conversion",
            direction=OutcomeDirection.IMPROVED,
        )
        assert o.is_positive

    def test_regressed_is_not_positive(self):
        o = OutcomeObservation(
            id="o1", project_id="p", story_id="S1",
            metric_name="signup_conversion",
            direction=OutcomeDirection.REGRESSED,
        )
        assert not o.is_positive
