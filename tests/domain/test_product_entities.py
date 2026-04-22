"""Domain tests for Phase C product-intelligence entities."""

from __future__ import annotations

from dataclasses import replace

from theswarm.domain.product import (
    InsightDigest,
    InsightKind,
    OKR,
    Policy,
    PolicyDecision,
    Proposal,
    ProposalStatus,
    Signal,
    SignalKind,
    SignalSeverity,
)
from theswarm.domain.product.entities import DigestItem, KeyResult


class TestProposal:
    def test_new_id_is_prefixed(self):
        assert Proposal.new_id().startswith("prop_")

    def test_dedup_key_is_stable(self):
        k1 = Proposal.dedup_key("demo", "Add dark mode")
        k2 = Proposal.dedup_key("demo", "Add dark mode")
        assert k1 == k2

    def test_dedup_key_is_case_insensitive(self):
        assert (
            Proposal.dedup_key("demo", "Add dark mode")
            == Proposal.dedup_key("demo", "ADD DARK MODE")
        )

    def test_dedup_key_varies_by_project(self):
        assert (
            Proposal.dedup_key("a", "title")
            != Proposal.dedup_key("b", "title")
        )

    def test_default_status_is_proposed(self):
        p = Proposal(id=Proposal.new_id(), project_id="demo", title="t")
        assert p.status is ProposalStatus.PROPOSED

    def test_approve_via_replace(self):
        p = Proposal(id="p1", project_id="demo", title="t")
        approved = replace(p, status=ProposalStatus.APPROVED, linked_story_id="s1")
        assert approved.status is ProposalStatus.APPROVED
        assert approved.linked_story_id == "s1"
        # original unchanged
        assert p.status is ProposalStatus.PROPOSED


class TestOKR:
    def test_new_id_is_prefixed(self):
        assert OKR.new_id().startswith("okr_")

    def test_key_results_are_tuple(self):
        kr = KeyResult(id=KeyResult.new_id(), description="ship v1")
        okr = OKR(id="o1", project_id="demo", objective="launch", key_results=(kr,))
        assert okr.key_results == (kr,)

    def test_okr_is_frozen(self):
        okr = OKR(id="o1", project_id="demo", objective="launch")
        # frozen dataclass — direct mutation raises
        try:
            okr.objective = "changed"  # type: ignore[misc]
        except Exception:
            return
        raise AssertionError("OKR should be frozen")


class TestPolicy:
    def test_default_has_no_rules(self):
        p = Policy(id="p1", project_id="demo")
        assert p.banned_terms == ()

    def test_banned_terms_stored(self):
        p = Policy(id="p1", project_id="demo", banned_terms=("crypto", "gambling"))
        assert "crypto" in p.banned_terms


class TestSignal:
    def test_new_id_is_prefixed(self):
        assert Signal.new_id().startswith("sig_")

    def test_fields(self):
        s = Signal(
            id="s1",
            project_id="demo",
            kind=SignalKind.COMPETITOR,
            severity=SignalSeverity.THREAT,
            title="rival ships X",
        )
        assert s.kind is SignalKind.COMPETITOR
        assert s.severity is SignalSeverity.THREAT


class TestInsightDigest:
    def test_new_id_is_prefixed(self):
        assert InsightDigest.new_id().startswith("dig_")

    def test_digest_items(self):
        item = DigestItem(kind=InsightKind.TREND, headline="LLMs get cheaper")
        from datetime import datetime, timezone
        d = InsightDigest(
            id="d1",
            project_id="demo",
            week_start=datetime(2026, 4, 20, tzinfo=timezone.utc),
            items=(item,),
        )
        assert d.items[0].headline.startswith("LLMs")


class TestPolicyDecisionEnum:
    def test_values(self):
        assert PolicyDecision.ALLOW.value == "allow"
        assert PolicyDecision.BLOCK.value == "block"
        assert PolicyDecision.REVIEW.value == "review"
