"""The E2E file is written with a fixture that sets up, and a repair says
what it changed.

Three of four local cycles on 2026-09-29 (cancel-tour, sold-out-list, and
country-stats the day before) wrote an E2E file whose every test failed at
setup — "TypeError: 'module' object is not callable" — and QA repaired it.
The prompt only said "Fixture `api_context` creates the Playwright API
context": each run invented its own. It now gives the fixture, the one
that sets up in the target's venv (3.11 and 3.12, pytest-playwright 0.9).

When a repair still happens, what it changed is kept: sold-out-list's PO
downgraded the day to yellow and asked engineering "to confirm what was
actually changed to go from TypeError … to passing". The diff rides the
E2E gate into the report the PO reads, and the log.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from theswarm.agents import qa

SETUP_ERRORS = """\
____________ ERROR at setup of test_feature_sold_out ____________
E   TypeError: 'module' object is not callable
=========== 3 errors in 0.40s ===========
"""
ALL_PASS = "=========== 3 passed in 0.50s ==========="
BLIND = "import pytest\nimport playwright\n\n@pytest.fixture\ndef api_context():\n    return playwright()\n"
FIXED = ("import pytest\nfrom playwright.sync_api import sync_playwright\n\n@pytest.fixture\n"
         "def api_context():\n    with sync_playwright() as p:\n        yield p.request.new_context()\n")


def test_the_prompt_gives_the_fixture_to_use():
    prompt = qa.E2E_PROMPT

    assert "from playwright.sync_api import sync_playwright" in prompt
    assert "def api_context():" in prompt
    assert "with sync_playwright() as p:" in prompt
    assert "p.request.new_context(base_url=BASE_URL)" in prompt
    assert "exactly" in prompt
    prompt.format(context="", endpoints="", port=8000)  # still a valid template


async def test_a_repair_keeps_what_it_changed(tmp_path):
    e2e_dir = tmp_path / "tests" / "e2e"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "test_api_e2e.py").write_text(BLIND)
    claude = MagicMock()
    claude.run_tests = AsyncMock(side_effect=[
        {"output": SETUP_ERRORS, "passed": False}, {"output": ALL_PASS, "passed": True}])
    claude.run = AsyncMock(return_value=SimpleNamespace(text=FIXED, total_tokens=90, cost_usd=0.03))
    process = MagicMock(returncode=None, wait=AsyncMock(return_value=0))
    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=process), \
         patch("theswarm.infrastructure.resilience.wait_for_http_ready",
               new_callable=AsyncMock, return_value=0.1):
        out = await qa.run_e2e_tests({"claude": claude, "workspace": str(tmp_path)})

    diff = out["e2e_repair_diff"]
    assert "-    return playwright()" in diff
    assert "+    with sync_playwright() as p:" in diff
    assert diff.startswith("--- test_api_e2e.py (written)")


def test_a_long_diff_is_cut():
    before = "\n".join(f"line {n}" for n in range(3000))
    after = "\n".join(f"LINE {n}" for n in range(3000))

    diff = qa._repair_diff(before, after)

    assert len(diff) <= qa.REPAIR_DIFF_LIMIT + 40
    assert diff.endswith("… (diff cut)")


async def test_the_report_carries_it_on_the_e2e_gate():
    state = {
        "e2e_repaired_from": "E   TypeError: 'module' object is not callable",
        "e2e_repair_diff": "--- test_api_e2e.py (written)\n+++ test_api_e2e.py (repaired)\n",
        "e2e_counts": {"passed": 3, "failed": 0, "errors": 0, "total": 3}, "e2e_passed": True,
        "test_counts": {"passed": 1, "failed": 0, "errors": 0, "total": 1}, "tests_passed": True,
    }
    with patch.object(qa, "_saved_artifacts", AsyncMock(return_value=[])):
        out = await qa.generate_demo_report(state)

    gate = out["demo_report"]["quality_gates"]["e2e_tests"]
    assert gate["repair_diff"].startswith("--- test_api_e2e.py (written)")


def test_the_state_declares_it():
    from theswarm.config import AgentState

    assert "e2e_repair_diff" in AgentState.__annotations__
