"""Tests for the TechLead bounded context entities + value objects."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from theswarm.domain.techlead.entities import (
    ADR,
    CriticalPath,
    DebtEntry,
    DepFinding,
    ReviewVerdict,
)
from theswarm.domain.techlead.value_objects import (
    ADRStatus,
    DebtSeverity,
    DepSeverity,
    ReviewDecision,
    ReviewOutcome,
)


class TestADR:
    def test_defaults(self):
        a = ADR(id="adr_1", project_id="demo", number=1, title="Use Event Bus")
        assert a.status is ADRStatus.PROPOSED
        assert a.supersedes is None
        assert a.tags == ()

    def test_slug_uses_number_and_lowercase_title(self):
        a = ADR(id="adr_1", project_id="demo", number=7, title="Use Event Bus!")
        assert a.slug == "0007-use-event-bus"

    def test_new_id_has_prefix(self):
        assert ADR.new_id().startswith("adr_")

    def test_frozen(self):
        a = ADR(id="adr_1", project_id="demo", number=1, title="t")
        with pytest.raises(Exception):
            a.title = "x"  # type: ignore[misc]


class TestDebtEntry:
    def test_defaults(self):
        d = DebtEntry(id="debt_1", project_id="demo", title="legacy auth")
        assert d.severity is DebtSeverity.MEDIUM
        assert d.resolved is False
        assert d.resolved_at is None

    def test_age_days_unresolved(self):
        created = datetime.now(timezone.utc) - timedelta(days=10)
        d = DebtEntry(id="debt_1", project_id="demo", title="t", created_at=created)
        assert d.age_days >= 10

    def test_age_days_resolved(self):
        created = datetime(2025, 1, 1, tzinfo=timezone.utc)
        resolved = datetime(2025, 1, 15, tzinfo=timezone.utc)
        d = DebtEntry(
            id="debt_1",
            project_id="demo",
            title="t",
            created_at=created,
            resolved=True,
            resolved_at=resolved,
        )
        assert d.age_days == 14

    def test_new_id_prefix(self):
        assert DebtEntry.new_id().startswith("debt_")


class TestDepFinding:
    def test_defaults(self):
        f = DepFinding(id="dep_1", project_id="demo", package="requests")
        assert f.severity is DepSeverity.INFO
        assert f.dismissed is False
        assert f.installed_version == ""

    def test_new_id_prefix(self):
        assert DepFinding.new_id().startswith("dep_")


class TestCriticalPath:
    def test_substring_match(self):
        c = CriticalPath(id="c_1", project_id="demo", pattern="auth")
        assert c.matches("src/theswarm/auth/token.py")
        assert not c.matches("README.md")

    def test_glob_match(self):
        c = CriticalPath(id="c_1", project_id="demo", pattern="src/**/db.py")
        assert c.matches("src/theswarm/infra/db.py")
        assert not c.matches("src/app.py")

    def test_empty_pattern_matches_nothing(self):
        c = CriticalPath(id="c_1", project_id="demo", pattern="")
        assert not c.matches("anything")


class TestReviewVerdict:
    def test_defaults(self):
        r = ReviewVerdict(id="rev_1", project_id="demo", pr_url="u")
        assert r.decision is ReviewDecision.APPROVE
        assert r.outcome is ReviewOutcome.UNKNOWN
        assert r.second_opinion is False
        assert r.outcome_at is None

    def test_new_id_prefix(self):
        assert ReviewVerdict.new_id().startswith("rev_")
