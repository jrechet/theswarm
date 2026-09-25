"""A failed E2E run says why, in the log and in the demo report.

Cycle 9d3174f41829 (2026-09-25): QA's E2E run ended "0 passed, 0 failed,
24 errors" and nothing kept the reason — the output lived only in QA's
state, and the workspace was deleted with the cycle.
"""

from __future__ import annotations

import logging

from theswarm.agents import qa

SETUP_ERRORS = """\
============================= test session starts ==============================
collected 24 items

tests/e2e/test_api_e2e.py::test_list_concerts ERROR                      [  4%]
tests/e2e/test_api_e2e.py::test_stats_cities ERROR                       [  8%]

==================================== ERRORS ====================================
_____________________ ERROR at setup of test_list_concerts _____________________
file tests/e2e/test_api_e2e.py, line 12
  def test_list_concerts(api_client):
E       fixture 'api_client' not found
>       available fixtures: cache, capfd, monkeypatch, tmp_path
_____________________ ERROR at setup of test_stats_cities ______________________
E       fixture 'api_client' not found
=========================== short test summary info ============================
ERROR tests/e2e/test_api_e2e.py::test_list_concerts
ERROR tests/e2e/test_api_e2e.py::test_stats_cities
============================== 24 errors in 0.31s ==============================
"""

COLLECTION = """\
==================================== ERRORS ====================================
_______________ ERROR collecting tests/e2e/test_api_e2e.py ______________________
ImportError while importing test module 'tests/e2e/test_api_e2e.py'.
E   ModuleNotFoundError: No module named 'requests'
=========================== short test summary info ============================
ERROR tests/e2e/test_api_e2e.py
"""


def test_the_excerpt_keeps_the_reason_and_drops_the_noise():
    excerpt = qa._failure_excerpt(SETUP_ERRORS)

    assert "fixture 'api_client' not found" in excerpt
    assert "ERROR at setup of test_list_concerts" in excerpt
    assert "test session starts" not in excerpt
    assert "available fixtures" not in excerpt


def test_a_collection_error_names_the_missing_module():
    excerpt = qa._failure_excerpt(COLLECTION)

    assert "No module named 'requests'" in excerpt
    assert "ERROR collecting" in excerpt


def test_the_excerpt_is_bounded():
    noisy = "\n".join(f"E   line {n}" for n in range(500))

    excerpt = qa._failure_excerpt(noisy, max_lines=14, max_chars=1500)

    assert len(excerpt.splitlines()) <= 14 and len(excerpt) <= 1500


def test_repeated_lines_are_kept_once():
    assert qa._failure_excerpt("E   boom\nE   boom\nE   boom") == "E   boom"


def test_a_passing_or_empty_run_has_no_excerpt():
    assert qa._failure_excerpt("") == ""
    assert qa._failure_excerpt("3 passed in 0.10s") == ""


async def test_the_demo_report_keeps_the_excerpt():
    state = {
        "workspace": "/ws",
        "e2e_counts": {"passed": 0, "failed": 0, "errors": 24, "total": 24},
        "e2e_passed": False,
        "e2e_failure_excerpt": "E       fixture 'api_client' not found",
        "test_counts": {"passed": 3, "failed": 0, "errors": 0, "total": 3},
        "tests_passed": True,
    }

    out = await qa.generate_demo_report(state)

    e2e = out["demo_report"]["quality_gates"]["e2e_tests"] if "quality_gates" in out["demo_report"] \
        else _find_e2e(out["demo_report"])
    assert e2e["failure_excerpt"] == "E       fixture 'api_client' not found"


def _find_e2e(report: dict) -> dict:
    for value in report.values():
        if isinstance(value, dict):
            if "e2e_tests" in value and isinstance(value["e2e_tests"], dict):
                return value["e2e_tests"]
    raise AssertionError(f"no e2e_tests section in {sorted(report)}")


def test_the_state_declares_the_excerpt():
    from theswarm.config import AgentState

    assert "e2e_failure_excerpt" in AgentState.__annotations__


async def test_a_failed_e2e_run_logs_and_returns_the_excerpt(tmp_path, caplog):
    from unittest.mock import AsyncMock, MagicMock, patch

    e2e_dir = tmp_path / "tests" / "e2e"
    e2e_dir.mkdir(parents=True)
    (e2e_dir / "test_api_e2e.py").write_text("def test_x(api_client):\n    pass\n")
    claude = MagicMock()
    claude.run_tests = AsyncMock(return_value={"output": SETUP_ERRORS, "passed": False})
    server = MagicMock()
    server.returncode = None
    server.wait = AsyncMock(return_value=0)
    caplog.set_level(logging.WARNING, logger="theswarm.agents.qa")

    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=server), \
         patch("theswarm.infrastructure.resilience.wait_for_http_ready",
               new_callable=AsyncMock, return_value=0.1):
        out = await qa.run_e2e_tests({"claude": claude, "workspace": str(tmp_path)})

    assert "fixture 'api_client' not found" in out["e2e_failure_excerpt"]
    assert "QA E2E failure excerpt" in caplog.text
    assert "fixture 'api_client' not found" in caplog.text
