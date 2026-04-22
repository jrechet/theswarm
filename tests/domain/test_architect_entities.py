"""Phase K domain tests — Architect entities."""

from __future__ import annotations

from theswarm.domain.architect.entities import (
    DirectionBrief,
    PavedRoadRule,
    PortfolioADR,
)
from theswarm.domain.architect.value_objects import (
    ADRStatus,
    BriefScope,
    RuleSeverity,
)


class TestPavedRoadRule:
    def test_required_is_blocking(self):
        r = PavedRoadRule(
            id="r1", name="python-uv", rule="use uv",
            severity=RuleSeverity.REQUIRED,
        )
        assert r.is_blocking

    def test_advisory_not_blocking(self):
        r = PavedRoadRule(
            id="r1", name="prefer-pytest", rule="pytest over unittest",
            severity=RuleSeverity.ADVISORY,
        )
        assert not r.is_blocking


class TestPortfolioADR:
    def test_empty_project_id_is_portfolio_wide(self):
        a = PortfolioADR(id="a1", title="x", project_id="")
        assert a.is_portfolio_wide

    def test_with_project_id_is_not_portfolio_wide(self):
        a = PortfolioADR(id="a1", title="x", project_id="proj-42")
        assert not a.is_portfolio_wide

    def test_accepted_is_active(self):
        a = PortfolioADR(
            id="a1", title="x", status=ADRStatus.ACCEPTED,
        )
        assert a.is_active

    def test_proposed_is_not_active(self):
        a = PortfolioADR(
            id="a1", title="x", status=ADRStatus.PROPOSED,
        )
        assert not a.is_active


class TestDirectionBrief:
    def test_project_scope(self):
        b = DirectionBrief(
            id="b1", title="2026-Q2",
            scope=BriefScope.PROJECT, project_id="p",
        )
        assert b.is_project_scoped

    def test_portfolio_scope(self):
        b = DirectionBrief(
            id="b1", title="2026-Q2", scope=BriefScope.PORTFOLIO,
        )
        assert not b.is_project_scoped
