"""QA runs the E2E file it wrote, and repairs it once when not one test can set up.

The file is written blind: no model call ever ran it. On 2026-09-25 two
cycles in five (9d3174f41829, b0075807f716) reported "0 passed, 0 failed,
24 errors" in under two seconds against a server that was ready and
answering 200. Every test errored in setup: the file did not fit the
application, and the report blamed nothing in particular. A failed
*assertion* is a verdict on the target and is left alone; a file that cannot
set up a single test is QA's own bug, and gets one repair round with pytest's
reason in hand.

The prompt also never named the port: `{{port}}` in a `.format` template
becomes `{port}`, and the `.replace("{{port}}", ...)` after it matched
nothing, so the model read a literal placeholder and guessed 8000.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from theswarm.agents import qa

SETUP_ERRORS = """\
tests/e2e/test_api_e2e.py::test_list_tours ERROR                         [ 50%]
_____________________ ERROR at setup of test_list_tours ________________________
E       fixture 'api_client' not found
=========================== short test summary info ============================
ERROR tests/e2e/test_api_e2e.py::test_list_tours
============================== 24 errors in 0.31s ==============================
"""
ALL_PASS = "============================== 24 passed in 1.20s =============================="
SOME_FAIL = """\
FAILED tests/e2e/test_api_e2e.py::test_create_tour - assert 422 == 201
========================= 2 failed, 22 passed in 1.40s =========================
"""
BLIND_FILE = "import pytest\n\ndef test_list_tours(api_client):\n    pass\n"
FIXED_FILE = "import pytest\n\ndef test_list_tours(api_context):\n    pass\n"


def _claude(outputs: list[str], repair_text: str | Exception = FIXED_FILE):
    claude = MagicMock()
    claude.run_tests = AsyncMock(
        side_effect=[{"output": out, "passed": "error" not in out and "failed" not in out}
                     for out in outputs],
    )
    if isinstance(repair_text, Exception):
        claude.run = AsyncMock(side_effect=repair_text)
    else:
        claude.run = AsyncMock(return_value=SimpleNamespace(
            text=repair_text, total_tokens=120, cost_usd=0.05,
        ))
    return claude


async def _run(tmp_path, claude):
    e2e_dir = tmp_path / "tests" / "e2e"
    e2e_dir.mkdir(parents=True, exist_ok=True)
    (e2e_dir / "test_api_e2e.py").write_text(BLIND_FILE)
    process = MagicMock()
    process.returncode = None
    process.wait = AsyncMock(return_value=0)
    with patch("theswarm.agents.qa._find_system_python", return_value="/usr/bin/python3"), \
         patch("asyncio.create_subprocess_exec", new_callable=AsyncMock, return_value=process), \
         patch("theswarm.infrastructure.resilience.wait_for_http_ready",
               new_callable=AsyncMock, return_value=0.1):
        return await qa.run_e2e_tests({"claude": claude, "workspace": str(tmp_path)})


def _file(tmp_path) -> str:
    return (tmp_path / "tests" / "e2e" / "test_api_e2e.py").read_text()


async def test_a_file_that_cannot_set_up_is_repaired_once_and_run_again(tmp_path):
    claude = _claude([SETUP_ERRORS, ALL_PASS])

    out = await _run(tmp_path, claude)

    assert out["e2e_passed"] is True
    assert out["e2e_counts"]["passed"] == 24
    assert _file(tmp_path) == FIXED_FILE  # stripped, one final newline, as the writer does
    assert "fixture 'api_client' not found" in out["e2e_repaired_from"]
    assert claude.run.await_count == 1 and claude.run_tests.await_count == 2
    assert out["tokens_used"] == 120 and out["cost_usd"] == 0.05


async def test_the_repair_prompt_carries_the_reason_the_file_and_the_port(tmp_path):
    claude = _claude([SETUP_ERRORS, ALL_PASS])

    with patch("theswarm.agents.qa.e2e_port", return_value=8123):
        await _run(tmp_path, claude)

    prompt = claude.run.await_args.args[0]
    assert "fixture 'api_client' not found" in prompt
    assert "def test_list_tours(api_client)" in prompt
    assert "http://127.0.0.1:8123" in prompt
    assert "{port}" not in prompt
    assert claude.run.await_args.kwargs["workdir"] == str(tmp_path)


async def test_failed_assertions_are_the_target_s_verdict_and_are_not_repaired(tmp_path):
    claude = _claude([SOME_FAIL])

    out = await _run(tmp_path, claude)

    assert out["e2e_passed"] is False and out["e2e_counts"]["failed"] == 2
    assert claude.run.await_count == 0
    assert _file(tmp_path) == BLIND_FILE
    assert out.get("e2e_repaired_from", "") == ""


async def test_a_repair_that_still_cannot_set_up_is_tried_once_only(tmp_path):
    claude = _claude([SETUP_ERRORS, SETUP_ERRORS])

    out = await _run(tmp_path, claude)

    assert out["e2e_passed"] is False
    assert claude.run.await_count == 1 and claude.run_tests.await_count == 2
    assert "fixture 'api_client' not found" in out["e2e_failure_excerpt"]
    assert out["e2e_repaired_from"]


async def test_a_repair_call_that_fails_keeps_the_first_verdict(tmp_path, caplog):
    claude = _claude([SETUP_ERRORS], repair_text=RuntimeError("SDK timed out"))
    caplog.set_level(logging.WARNING, logger="theswarm.agents.qa")

    out = await _run(tmp_path, claude)

    assert out["e2e_passed"] is False and out["e2e_counts"]["errors"] == 24
    assert claude.run_tests.await_count == 1
    assert _file(tmp_path) == BLIND_FILE
    assert out.get("e2e_repaired_from", "") == ""
    assert "E2E repair unavailable" in caplog.text


async def test_a_repair_answer_without_code_keeps_the_first_file(tmp_path):
    claude = _claude([SETUP_ERRORS], repair_text="I could not find the fixture.")

    out = await _run(tmp_path, claude)

    assert _file(tmp_path) == BLIND_FILE
    assert claude.run_tests.await_count == 1
    assert out["e2e_passed"] is False


async def test_a_fatal_claude_error_still_aborts(tmp_path):
    import pytest

    from theswarm.tools.claude import ClaudeFatalError

    claude = _claude([SETUP_ERRORS], repair_text=ClaudeFatalError("window exhausted"))

    with pytest.raises(ClaudeFatalError):
        await _run(tmp_path, claude)


def test_the_setup_signature_is_every_test_errored_and_none_ran():
    assert qa._e2e_file_cannot_set_up({"passed": 0, "failed": 0, "errors": 24, "total": 24})
    assert qa._e2e_file_cannot_set_up({"passed": 0, "failed": 0, "errors": 1, "total": 1})
    assert not qa._e2e_file_cannot_set_up({"passed": 22, "failed": 0, "errors": 2, "total": 24})
    assert not qa._e2e_file_cannot_set_up({"passed": 0, "failed": 3, "errors": 0, "total": 3})
    assert not qa._e2e_file_cannot_set_up({"passed": 0, "failed": 0, "errors": 0, "total": 0})


async def test_the_writer_prompt_names_the_real_port(tmp_path):
    claude = MagicMock()
    claude.run = AsyncMock(return_value=SimpleNamespace(
        text=FIXED_FILE, total_tokens=10, cost_usd=0.01,
    ))

    with patch("theswarm.agents.qa.e2e_port", return_value=8123):
        await qa.write_e2e_tests({"claude": claude, "workspace": str(tmp_path)})

    prompt = claude.run.await_args.args[0]
    assert "http://127.0.0.1:8123" in prompt
    assert "{port}" not in prompt and "{{port}}" not in prompt


async def test_the_demo_report_says_the_file_was_repaired():
    state = {
        "workspace": "/ws",
        "e2e_counts": {"passed": 24, "failed": 0, "errors": 0, "total": 24},
        "e2e_passed": True,
        "e2e_repaired_from": "E       fixture 'api_client' not found",
        "test_counts": {"passed": 3, "failed": 0, "errors": 0, "total": 3},
        "tests_passed": True,
    }

    out = await qa.generate_demo_report(state)

    e2e = out["demo_report"]["quality_gates"]["e2e_tests"]
    assert e2e["status"] == "pass"
    assert e2e["repaired_from"] == "E       fixture 'api_client' not found"


def test_the_state_declares_the_repair_key():
    from theswarm.config import AgentState

    assert "e2e_repaired_from" in AgentState.__annotations__
