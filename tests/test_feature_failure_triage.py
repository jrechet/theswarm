"""A failing feature test is triaged before the build is called broken.

The E2E file is written blind. On past-concerts-toggle (2026-09-29) three
of its `test_feature_*` tests counted `class="concert-card` as a
substring — `concert-card-date`, `concert-card-next` match too — and found
24 cards where the seed makes 6: the verdict read "broken" off the tests'
own mistake. One call reads the failing tests, pytest's lines and the
app's code, and says for each whether the app or the test is wrong. When
every failure is the test's, the gate is `inconclusive` and the verdict
`unverified` — never `verified`: triage can soften a "broken", not confirm
anything, and nothing is rewritten to pass.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from theswarm import evals
from theswarm.agents import qa
from theswarm.application.services.report_generator import _qa_quality_gates
from theswarm.domain.reporting.value_objects import QualityStatus

E2E_FILE = '''\
import pytest

SEEDED_TOTAL_CONCERTS = 6


def test_feature_dashboard_concerts_default_includes_past(api_context):
    html = api_context.get("/api/v1/dashboard/concerts").text()
    assert html.count('class="concert-card') == SEEDED_TOTAL_CONCERTS


def test_list_tours(api_context):
    assert api_context.get("/api/v1/tours/").ok
'''
OUTPUT = """\
FAILED tests/e2e/test_api_e2e.py::test_feature_dashboard_concerts_default_includes_past - assert 24 == 6
E   assert 24 == 6
"""
FAILING = {"status": "fail", "passed": 2, "failed": 1,
           "reason": "failed: test_feature_dashboard_concerts_default_includes_past"}


def _claude(verdicts):
    claude = MagicMock()
    claude.run = AsyncMock(return_value=SimpleNamespace(
        structured={"verdicts": verdicts}, text="", total_tokens=40, cost_usd=0.02))
    return claude


def _file(tmp_path):
    path = tmp_path / "tests" / "e2e" / "test_api_e2e.py"
    path.parent.mkdir(parents=True)
    path.write_text(E2E_FILE)
    return str(path)


async def test_failures_that_are_the_tests_own_make_the_gate_inconclusive(tmp_path):
    claude = _claude([{"test": "test_feature_dashboard_concerts_default_includes_past", "fault": "test",
                       "why": "counts a class prefix: concert-card-date matches too"}])

    gate = await qa._triage_feature_failures(claude, str(tmp_path), _file(tmp_path), FAILING, OUTPUT)

    assert gate["status"] == "inconclusive"
    assert "the tests are wrong, not the app" in gate["reason"]
    assert "concert-card-date matches too" in gate["reason"]
    prompt = claude.run.await_args.args[0]
    assert "def test_feature_dashboard_concerts_default_includes_past" in prompt
    assert "def test_list_tours" not in prompt  # only the failing feature tests
    assert "assert 24 == 6" in prompt


async def test_a_failure_blamed_on_the_app_stays_a_failure(tmp_path):
    claude = _claude([{"test": "test_feature_dashboard_concerts_default_includes_past", "fault": "app",
                       "why": "past concerts are listed although the toggle hides them"}])

    gate = await qa._triage_feature_failures(claude, str(tmp_path), _file(tmp_path), FAILING, OUTPUT)

    assert gate["status"] == "fail"
    assert "the app: test_feature_dashboard_concerts_default_includes_past: past concerts are listed" in gate["reason"]


async def test_a_triage_that_names_no_failing_test_changes_nothing(tmp_path):
    claude = _claude([{"test": "test_something_else", "fault": "test", "why": "?"}])

    gate = await qa._triage_feature_failures(claude, str(tmp_path), _file(tmp_path), FAILING, OUTPUT)

    assert gate == FAILING


async def test_a_triage_call_that_fails_leaves_the_failure(tmp_path):
    claude = MagicMock()
    claude.run = AsyncMock(side_effect=RuntimeError("timeout"))

    gate = await qa._triage_feature_failures(claude, str(tmp_path), _file(tmp_path), FAILING, OUTPUT)

    assert gate == FAILING


async def test_a_passing_gate_is_not_triaged(tmp_path):
    claude = _claude([])
    passing = {"status": "pass", "passed": 3, "failed": 0, "reason": "3 feature test(s) passed"}

    assert await qa._triage_feature_failures(claude, str(tmp_path), _file(tmp_path), passing, "") == passing
    claude.run.assert_not_awaited()


def test_an_inconclusive_feature_test_leaves_the_verdict_unverified():
    assert evals.behaviour_of({"feature_e2e": "inconclusive", "feature_pages": "pass"}) == "unverified"
    assert evals.behaviour_of({"feature_e2e": "inconclusive", "feature_pages": "fail"}) == "broken"


def test_the_report_shows_it_as_a_warning_with_the_reason():
    (gate,) = _qa_quality_gates({"feature_e2e": {
        "status": "inconclusive", "passed": 2, "failed": 1,
        "reason": "the tests are wrong, not the app: counts a class prefix"}})

    assert gate.status == QualityStatus.WARN
    assert "counts a class prefix" in gate.detail
