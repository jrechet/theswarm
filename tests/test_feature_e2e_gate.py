"""The behaviour verdict reads the tests of the feature delivered (#79, #85).

QA wrote its E2E file once per workspace and reused it forever: it tested
the API as it was when first written, never the feature a cycle built. On
2026-09-28 the harness run on price-range scored the build "broken" off a
stale test of the tours listing (`?status=planning` — the status is
`planned`; the app rightly answered 422). The file is rewritten when a
cycle delivered PRs, its tests of the feature's pages are named
`test_feature_*`, and the verdict reads those (`feature_e2e`) and the page
walk (`feature_pages`) — a wrong guess about an unrelated endpoint still
shows in the E2E gate, and flips nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

from theswarm import evals
from theswarm.agents import qa
from theswarm.agents.qa import feature_e2e_gate

PAGES = [("/api/v1/concerts/by-price", "feature_pr_416_concerts_by_price")]
PRS = [{"number": 416, "head_sha": "abc", "title": "[#412] Filter the concerts by ticket price"}]

OUTPUT = """\
tests/e2e/test_api_e2e.py::test_feature_price_range_filters PASSED       [  5%]
tests/e2e/test_api_e2e.py::test_feature_price_range_rejects_min_above_max[0-10] PASSED [ 10%]
tests/e2e/test_api_e2e.py::test_list_tours FAILED                        [ 15%]
tests/e2e/test_api_e2e.py::test_get_missing_tour PASSED                  [ 20%]
=========================== short test summary info ============================
FAILED tests/e2e/test_api_e2e.py::test_list_tours - AssertionError: assert 422 == 200
==================== 1 failed, 3 passed in 1.20s ====================
"""


# ── The gate ─────────────────────────────────────────────────────────


def test_the_feature_s_tests_passing_is_a_pass_whatever_else_failed():
    gate = feature_e2e_gate(OUTPUT)

    assert gate["status"] == "pass"
    assert gate["passed"] == 2 and gate["failed"] == 0
    assert gate["reason"] == "2 feature test(s) passed"


def test_a_failing_feature_test_fails_the_gate_and_names_itself():
    output = OUTPUT.replace("test_feature_price_range_filters PASSED", "test_feature_price_range_filters FAILED") + \
        "FAILED tests/e2e/test_api_e2e.py::test_feature_price_range_filters - assert 0 == 3\n"

    gate = feature_e2e_gate(output)

    assert gate["status"] == "fail" and gate["failed"] == 1
    assert "test_feature_price_range_filters" in gate["reason"]


def test_an_error_in_a_feature_test_is_a_failure():
    gate = feature_e2e_gate("ERROR tests/e2e/test_api_e2e.py::test_feature_x - fixture 'api' not found\n")

    assert gate["status"] == "fail"


def test_no_feature_test_is_not_run():
    gate = feature_e2e_gate("tests/e2e/test_api_e2e.py::test_list_tours PASSED\n1 passed\n")

    assert gate == {"status": "not_run", "passed": 0, "failed": 0,
                    "reason": "the E2E file names no test_feature_* test"}


# ── QA writes the feature's tests, every cycle that built something ──


def _claude(code: str = "import pytest\n\ndef test_feature_x():\n    assert True\n"):
    @dataclass
    class Result:
        text: str
        total_tokens: int = 10
        cost_usd: float = 0.01

    claude = MagicMock()
    claude.run = AsyncMock(return_value=Result(code))
    return claude


async def test_the_prompt_names_the_feature_and_asks_for_its_tests(tmp_path):
    claude = _claude()
    with patch("theswarm.agents.qa_feature_pages.feature_pages", AsyncMock(return_value=PAGES)), \
         patch("theswarm.agents.qa.e2e_port", return_value=8123):
        out = await qa.write_e2e_tests({"claude": claude, "workspace": str(tmp_path),
                                        "github": AsyncMock(), "prs": PRS})

    prompt = claude.run.await_args.args[0]
    assert "## The feature this cycle delivered" in prompt
    assert "/api/v1/concerts/by-price" in prompt and "#416" in prompt
    assert "test_feature_" in prompt
    assert out["feature_pages"] == PAGES


async def test_a_cycle_that_built_something_rewrites_a_stale_file(tmp_path):
    stale = tmp_path / "tests" / "e2e" / "test_api_e2e.py"
    stale.parent.mkdir(parents=True)
    stale.write_text("import pytest\n\ndef test_list_tours():\n    assert 'planning'\n" * 5)
    claude = _claude()

    with patch("theswarm.agents.qa_feature_pages.feature_pages", AsyncMock(return_value=PAGES)), \
         patch("theswarm.agents.qa.e2e_port", return_value=8123):
        await qa.write_e2e_tests({"claude": claude, "workspace": str(tmp_path),
                                  "github": AsyncMock(), "prs": PRS})

    claude.run.assert_awaited_once()
    assert "test_feature_x" in stale.read_text()


async def test_the_captures_reuse_the_pages_qa_already_read(monkeypatch):
    lookup = AsyncMock(return_value=[("/other", "x")])

    async def nothing(state):
        return {"tokens_used": 0, "seen": state.get("feature_pages")}

    monkeypatch.setattr(qa, "capture_demo_screenshots", nothing)
    monkeypatch.setattr(qa, "record_demo_video", nothing)
    monkeypatch.setattr(qa, "capture_before_after_per_story", nothing)
    monkeypatch.setattr(qa, "record_story_video", nothing)
    monkeypatch.setattr(qa, "_capture_concurrency", lambda: 1)
    with patch("theswarm.agents.qa_feature_pages.feature_pages", lookup):
        out = await qa.run_captures({"workspace": "/ws", "github": object(), "prs": PRS,
                                     "feature_pages": PAGES})

    lookup.assert_not_awaited()
    assert out["feature_pages"] == PAGES


async def test_the_report_carries_the_feature_e2e_gate():
    state = {
        "workspace": "/ws",
        "test_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1}, "tests_passed": True,
        "e2e_counts": {"passed": 3, "failed": 1, "errors": 0, "total": 4}, "e2e_passed": False,
        "e2e_feature": feature_e2e_gate(OUTPUT),
    }
    with patch.object(qa, "_saved_artifacts", AsyncMock(return_value=[])):
        out = await qa.generate_demo_report(state)

    gates = out["demo_report"]["quality_gates"]
    assert gates["e2e_tests"]["status"] == "fail"  # still said
    assert gates["feature_e2e"]["status"] == "pass"


def test_the_run_state_declares_the_feature_gate():
    from theswarm.config import AgentState

    assert "e2e_feature" in AgentState.__annotations__


# ── The verdict ──────────────────────────────────────────────────────


def test_an_unrelated_e2e_failure_does_not_break_the_verdict():
    qa_gates = {"e2e_tests": "fail", "feature_e2e": "pass", "feature_pages": "pass"}

    assert evals.behaviour_of(qa_gates) == "verified"


def test_the_feature_s_own_test_failing_breaks_it():
    assert evals.behaviour_of({"feature_e2e": "fail", "feature_pages": "pass"}) == "broken"


def test_one_confirmation_and_no_contradiction_is_verified():
    """A POST-only feature has no page to walk; its own tests passing on
    the running app confirm it."""
    assert evals.behaviour_of({"feature_e2e": "pass", "feature_pages": "not_run"}) == "verified"


def test_nothing_about_the_feature_ran_is_unverified():
    assert evals.behaviour_of({"e2e_tests": "pass", "feature_pages": "not_run"}) == "unverified"
    assert evals.behaviour_of({}) == "unverified"


def test_the_prompt_warns_against_counting_html_by_substring():
    """past-concerts-toggle's feature tests counted `class="concert-card` as
    a substring — `concert-card-date`, `-next` … match too — and a good
    build read "broken" until the triage caught it (test_feature_failure_triage)."""
    prompt = qa.E2E_PROMPT

    assert "substring" in prompt and "JSON" in prompt
