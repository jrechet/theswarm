"""Every failing E2E test is triaged, not only the feature's.

The whole-file E2E gate is not part of the behaviour verdict, but it
colours the report and the PO reads it: `'X-Total-Count' in headers`
(Playwright lower-cases names) and a nested `venue` the schema never had
made it red for days, and the PO reported a pagination regression that did
not exist. The failures that are not `test_feature_*` get the same triage:
all of them the tests' own mistake → the gate is `inconclusive` (a
warning, with why); any blamed on the app → it stays red.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from theswarm.agents import qa
from theswarm.application.services.report_generator import _qa_quality_gates
from theswarm.domain.reporting.value_objects import QualityStatus

E2E_FILE = '''\
def test_feature_cities(api_context):
    assert api_context.get("/api/v1/tours/1/cities").ok


def test_get_concerts_list_returns_total_count_header(api_context):
    response = api_context.get("/api/v1/concerts/")
    assert "X-Total-Count" in response.headers
'''
OUTPUT = """\
tests/e2e/test_api_e2e.py::test_feature_cities PASSED
tests/e2e/test_api_e2e.py::test_get_concerts_list_returns_total_count_header FAILED
E   AssertionError: assert 'X-Total-Count' in {'content-length': '1954', 'x-total-count': '6'}
FAILED tests/e2e/test_api_e2e.py::test_get_concerts_list_returns_total_count_header - AssertionError
=========== 1 failed, 1 passed in 0.50s ===========
"""


def _claude(fault):
    claude = MagicMock()
    claude.run = AsyncMock(return_value=SimpleNamespace(
        structured={"verdicts": [{"test": "test_get_concerts_list_returns_total_count_header",
                                  "fault": fault, "why": "Playwright lower-cases header names"}]},
        text="", total_tokens=20, cost_usd=0.02))
    return claude


def _file(tmp_path):
    path = tmp_path / "tests" / "e2e" / "test_api_e2e.py"
    path.parent.mkdir(parents=True)
    path.write_text(E2E_FILE)
    return str(path)


async def test_failures_that_are_the_tests_own_make_the_gate_inconclusive(tmp_path):
    claude = _claude("test")

    triage = await qa._triage_other_failures(claude, str(tmp_path), _file(tmp_path), OUTPUT)

    assert triage["status"] == "inconclusive"
    assert "the tests are wrong, not the app" in triage["reason"]
    assert "lower-cases header names" in triage["reason"]
    prompt = claude.run.await_args.args[0]
    assert "def test_get_concerts_list_returns_total_count_header" in prompt
    assert "def test_feature_cities" not in prompt  # the feature's tests have their own triage


async def test_a_failure_blamed_on_the_app_keeps_it_red(tmp_path):
    triage = await qa._triage_other_failures(_claude("app"), str(tmp_path), _file(tmp_path), OUTPUT)

    assert triage["status"] == "fail" and "the app:" in triage["reason"]


async def test_nothing_else_failing_is_no_call(tmp_path):
    claude = _claude("test")
    passing = OUTPUT.replace("FAILED", "PASSED").replace("1 failed, ", "")

    assert await qa._triage_other_failures(claude, str(tmp_path), _file(tmp_path), passing) is None
    claude.run.assert_not_awaited()


async def test_the_report_says_inconclusive_with_why():
    state = {
        "e2e_counts": {"passed": 23, "failed": 1, "errors": 0, "total": 24}, "e2e_passed": False,
        "e2e_triage": {"status": "inconclusive",
                       "reason": "the tests are wrong, not the app: header names are lower-cased"},
        "test_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1}, "tests_passed": True,
    }
    with patch.object(qa, "_saved_artifacts", AsyncMock(return_value=[])):
        out = await qa.generate_demo_report(state)

    gate = out["demo_report"]["quality_gates"]["e2e_tests"]
    assert gate["status"] == "inconclusive"
    (stored,) = [g for g in _qa_quality_gates(out["demo_report"]["quality_gates"]) if g.name == "e2e_tests"]
    assert stored.status == QualityStatus.WARN and "lower-cased" in stored.detail


def test_the_state_declares_it():
    from theswarm.config import AgentState

    assert "e2e_triage" in AgentState.__annotations__
