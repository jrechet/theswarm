"""Tests for the PolicyFilter."""

from __future__ import annotations

import pytest

from theswarm.application.services.policy_filter import PolicyFilter
from theswarm.domain.product.entities import Policy
from theswarm.domain.product.value_objects import PolicyDecision
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.product import SQLitePolicyRepository


@pytest.fixture()
async def repo(tmp_path):
    conn = await init_db(str(tmp_path / "policy.db"))
    yield SQLitePolicyRepository(conn)
    await conn.close()


class TestPolicyFilter:
    async def test_allow_when_no_policy(self, repo):
        f = PolicyFilter(repo)
        v = await f.evaluate(project_id="unknown", text="anything")
        assert v.decision is PolicyDecision.ALLOW

    async def test_blocks_on_banned_term(self, repo):
        await repo.upsert(
            Policy(id="p", project_id="demo", banned_terms=("crypto",)),
        )
        f = PolicyFilter(repo)
        v = await f.evaluate(project_id="demo", text="Ship a crypto wallet")
        assert v.decision is PolicyDecision.BLOCK
        assert "crypto" in v.matched_banned
        assert "banned" in v.reason

    async def test_review_required(self, repo):
        await repo.upsert(
            Policy(
                id="p", project_id="demo",
                require_review_terms=("authentication",),
            ),
        )
        f = PolicyFilter(repo)
        v = await f.evaluate(
            project_id="demo", text="Improve the authentication flow",
        )
        assert v.decision is PolicyDecision.REVIEW
        assert "authentication" in v.matched_review

    async def test_banned_overrides_review(self, repo):
        await repo.upsert(
            Policy(
                id="p", project_id="demo",
                banned_terms=("gambling",),
                require_review_terms=("authentication",),
            ),
        )
        f = PolicyFilter(repo)
        v = await f.evaluate(
            project_id="demo",
            text="gambling site with authentication",
        )
        assert v.decision is PolicyDecision.BLOCK

    async def test_case_insensitive(self, repo):
        await repo.upsert(
            Policy(id="p", project_id="demo", banned_terms=("Crypto",)),
        )
        f = PolicyFilter(repo)
        v = await f.evaluate(project_id="demo", text="build a CRYPTO exchange")
        assert v.decision is PolicyDecision.BLOCK
