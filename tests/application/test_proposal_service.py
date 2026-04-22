"""Tests for ProposalService (Phase C)."""

from __future__ import annotations

import pytest

from theswarm.application.services.policy_filter import PolicyFilter
from theswarm.application.services.proposal_service import ProposalService
from theswarm.domain.product.entities import Policy, Signal
from theswarm.domain.product.value_objects import (
    ProposalStatus,
    SignalKind,
    SignalSeverity,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.product import (
    SQLitePolicyRepository,
    SQLiteProposalRepository,
    SQLiteSignalRepository,
)


@pytest.fixture()
async def ctx(tmp_path):
    db = await init_db(str(tmp_path / "proposal.db"))
    prop_repo = SQLiteProposalRepository(db)
    policy_repo = SQLitePolicyRepository(db)
    signal_repo = SQLiteSignalRepository(db)
    pf = PolicyFilter(policy_repo)
    svc = ProposalService(prop_repo, pf, signal_repo=signal_repo)
    yield svc, prop_repo, policy_repo, signal_repo
    await db.close()


def _mk_signal(**kwargs) -> Signal:
    defaults = dict(
        id=Signal.new_id(),
        project_id="demo",
        kind=SignalKind.COMPETITOR,
        severity=SignalSeverity.OPPORTUNITY,
        title="rival ships dark mode",
        body="they added it last night",
        source_url="https://example.com/a",
    )
    defaults.update(kwargs)
    return Signal(**defaults)


class TestProposeFromSignal:
    async def test_creates_proposal_and_records_signal(self, ctx):
        svc, prop_repo, _, signal_repo = ctx
        p = await svc.propose_from_signal(
            project_id="demo", signal=_mk_signal(),
            codename="Alice",
        )
        assert p.status is ProposalStatus.PROPOSED
        assert p.codename == "Alice"
        assert p.source_url == "https://example.com/a"
        # Signal was persisted too
        signals = await signal_repo.list_for_project("demo")
        assert len(signals) == 1

    async def test_rationale_includes_kind_label(self, ctx):
        svc, _, _, _ = ctx
        p = await svc.propose_from_signal(
            project_id="demo",
            signal=_mk_signal(kind=SignalKind.CUSTOMER),
        )
        assert "Customer" in p.rationale


class TestApprove:
    async def test_happy_path_approved(self, ctx):
        svc, prop_repo, _, _ = ctx
        p = await svc.propose_from_signal(
            project_id="demo", signal=_mk_signal(),
        )
        result = await svc.approve(p.id, note="let's ship", linked_story_id="st_1")
        assert result.proposal is not None
        assert result.proposal.status is ProposalStatus.APPROVED
        assert result.proposal.linked_story_id == "st_1"

    async def test_blocked_by_policy(self, ctx):
        svc, prop_repo, policy_repo, _ = ctx
        await policy_repo.upsert(
            Policy(id="pol", project_id="demo", banned_terms=("dark mode",)),
        )
        p = await svc.propose_from_signal(
            project_id="demo", signal=_mk_signal(),
        )
        result = await svc.approve(p.id)
        assert result.proposal is not None
        assert result.proposal.status is ProposalStatus.REJECTED
        assert "policy" in result.proposal.decision_note

    async def test_requires_review_escalates_to_asked(self, ctx):
        svc, prop_repo, policy_repo, _ = ctx
        await policy_repo.upsert(
            Policy(
                id="pol", project_id="demo",
                require_review_terms=("dark mode",),
            ),
        )
        p = await svc.propose_from_signal(
            project_id="demo", signal=_mk_signal(),
        )
        result = await svc.approve(p.id)
        assert result.proposal is not None
        assert result.proposal.status is ProposalStatus.ASKED

    async def test_review_can_be_forced_with_note(self, ctx):
        svc, prop_repo, policy_repo, _ = ctx
        await policy_repo.upsert(
            Policy(
                id="pol", project_id="demo",
                require_review_terms=("dark mode",),
            ),
        )
        p = await svc.propose_from_signal(
            project_id="demo", signal=_mk_signal(),
        )
        result = await svc.approve(p.id, note="human override: safe")
        assert result.proposal is not None
        assert result.proposal.status is ProposalStatus.APPROVED


class TestRejectDeferAsk:
    async def test_reject(self, ctx):
        svc, _, _, _ = ctx
        p = await svc.propose_from_signal(
            project_id="demo", signal=_mk_signal(),
        )
        r = await svc.reject(p.id, note="not aligned")
        assert r.proposal is not None
        assert r.proposal.status is ProposalStatus.REJECTED

    async def test_defer(self, ctx):
        svc, _, _, _ = ctx
        p = await svc.propose_from_signal(
            project_id="demo", signal=_mk_signal(),
        )
        r = await svc.defer(p.id, note="Q3")
        assert r.proposal is not None
        assert r.proposal.status is ProposalStatus.DEFERRED

    async def test_ask(self, ctx):
        svc, _, _, _ = ctx
        p = await svc.propose_from_signal(
            project_id="demo", signal=_mk_signal(),
        )
        r = await svc.ask(p.id, note="need legal")
        assert r.proposal is not None
        assert r.proposal.status is ProposalStatus.ASKED


class TestInbox:
    async def test_lists_only_pending(self, ctx):
        svc, prop_repo, _, _ = ctx
        # two proposals: approve one, leave the other
        p1 = await svc.propose_from_signal(
            project_id="demo", signal=_mk_signal(title="a"),
        )
        p2 = await svc.propose_from_signal(
            project_id="demo", signal=_mk_signal(title="b"),
        )
        await svc.approve(p1.id)
        inbox = await svc.list_inbox("demo")
        assert {p.title for p in inbox} == {"b"}
