"""A Claude call that fails is a step skipped, not a cycle lost (#147).

Two cycles in a row died the same way: `bbab1b4ad6e9` on the review of a
500-line diff (18.9k-char prompt, 180s then 234s) and `794a644f6889` on QA's
E2E-file generation (90s then 117s). Each time the CLI wrapper's
RuntimeError propagated out of the sub-phase: no QA, no report, no memory
save, the PR left open unreviewed — for a call that was optional.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from theswarm.agents import qa as qa_mod
from theswarm.agents.techlead import (
    REVIEW_TIMEOUT_CEILING_SECONDS,
    REVIEW_TIMEOUT_FLOOR_SECONDS,
    _review_timeout,
    poll_and_review_prs,
)
from theswarm.config import AgentState
from theswarm.tools.claude import ClaudeFatalError

REVIEW = '{"decision": "APPROVE", "summary": "fine", "issues": []}'


def _pr(number: int) -> dict:
    return {"number": number, "title": f"[#{number}] t", "body": "", "head": f"feat/{number}", "head_sha": f"s{number}"}


def _github(prs: list[dict]) -> AsyncMock:
    gh = AsyncMock()
    gh.get_open_prs = AsyncMock(return_value=prs)
    gh.get_pr_files = AsyncMock(return_value=[{"filename": "a.py", "patch": "+x", "additions": 1, "deletions": 0, "status": "modified"}])
    return gh


class TestTheReviewBudget:
    def test_a_small_prompt_keeps_the_floor(self):
        assert _review_timeout(1_000) == REVIEW_TIMEOUT_FLOOR_SECONDS == 180

    def test_a_500_line_diff_gets_room(self):
        # bbab1b4ad6e9: 18,900 chars timed out at 180s and at 234s.
        assert _review_timeout(18_900) >= 340

    def test_the_cli_ceiling_still_applies(self):
        assert _review_timeout(1_000_000) == REVIEW_TIMEOUT_CEILING_SECONDS == 780

    async def test_the_call_carries_the_scaled_timeout(self):
        claude = AsyncMock()
        claude.run = AsyncMock(return_value=SimpleNamespace(text=REVIEW, total_tokens=1, cost_usd=0.1))
        gh = _github([_pr(1)])
        gh.get_pr_files = AsyncMock(return_value=[
            {"filename": "a.py", "patch": "+x\n" * 4000, "additions": 4000, "deletions": 0, "status": "modified"},
        ])

        await poll_and_review_prs({"github": gh, "claude": claude})

        prompt = claude.run.await_args.args[0]
        assert claude.run.await_args.kwargs["timeout"] == _review_timeout(len(prompt))
        assert claude.run.await_args.kwargs["timeout"] > REVIEW_TIMEOUT_FLOOR_SECONDS


class TestAFailingReview:
    async def test_is_skipped_and_the_loop_goes_on(self):
        async def run(prompt, **kw):
            if "#146" in prompt:
                raise RuntimeError("Claude CLI failed twice and no usable API credential is available")
            return SimpleNamespace(text=REVIEW, total_tokens=1, cost_usd=0.1)

        claude = AsyncMock(); claude.run = AsyncMock(side_effect=run)
        reviewed: list[str] = []

        result = await poll_and_review_prs({
            "github": _github([_pr(146), _pr(147)]), "claude": claude, "reviewed_prs": reviewed,
        })

        assert [r["pr_number"] for r in result["reviews"]] == [147]
        assert result["skipped_prs"] == [146]
        assert reviewed == ["147@s147"]  # #146 is read again next pass
        assert "146" in result["result"]

    async def test_a_fatal_claude_error_still_aborts(self):
        claude = AsyncMock()
        claude.run = AsyncMock(side_effect=ClaudeFatalError("Claude subscription exhausted: resets 5pm"))

        with pytest.raises(ClaudeFatalError):
            await poll_and_review_prs({"github": _github([_pr(1)]), "claude": claude})

    def test_the_state_key_is_declared(self):
        assert "skipped_prs" in AgentState.__annotations__


class TestAFailingE2EGeneration:
    def _state(self, tmp_path, claude) -> dict:
        (tmp_path / "src").mkdir()
        return {"workspace": str(tmp_path), "claude": claude, "context": "ctx", "github": None}

    async def test_is_skipped_not_fatal(self, tmp_path):
        claude = AsyncMock()
        claude.run = AsyncMock(side_effect=RuntimeError("Claude CLI failed twice and no usable API credential"))

        result = await qa_mod.write_e2e_tests(self._state(tmp_path, claude))

        assert result["tokens_used"] == 0
        assert not (tmp_path / "tests" / "e2e" / "test_api_e2e.py").exists()

    async def test_a_fatal_claude_error_still_aborts(self, tmp_path):
        claude = AsyncMock()
        claude.run = AsyncMock(side_effect=ClaudeFatalError("Claude subscription exhausted"))

        with pytest.raises(ClaudeFatalError):
            await qa_mod.write_e2e_tests(self._state(tmp_path, claude))

    async def test_the_generation_gets_a_real_budget(self, tmp_path):
        """The two successful generations on this repo took ~2m50s wall; 90s
        was the CLI default, and 794a644f6889 died on it."""
        claude = AsyncMock()
        claude.run = AsyncMock(return_value=SimpleNamespace(text="import pytest\n", total_tokens=1, cost_usd=0.1))

        await qa_mod.write_e2e_tests(self._state(tmp_path, claude))

        assert claude.run.await_args.kwargs["timeout"] == qa_mod.E2E_GENERATION_TIMEOUT_SECONDS
        assert qa_mod.E2E_GENERATION_TIMEOUT_SECONDS >= 240
