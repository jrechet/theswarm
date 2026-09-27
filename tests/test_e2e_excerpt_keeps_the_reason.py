"""A failed E2E run's excerpt says why, not only which test.

The daily run of 2026-09-26 (pagination, cycle 1418b48f3180) logged
"30 passed, 1 failed" and an excerpt of one line — the summary's
`FAILED tests/e2e/test_api_e2e.py::test_get_concerts_list_default_pagination`.
`run_tests` hands back only the last 5000 characters of pytest's output,
and the `E   …` lines that say what went wrong sit before the tail the
summary takes; the workspace is gone after the cycle, so nothing else
kept them. The E2E run now keeps its whole output for the excerpt, and a
single long assertion dump cannot eat the excerpt's budget.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from theswarm.agents import qa


def _output(e_line: str) -> str:
    passed = "".join(
        f"tests/e2e/test_api_e2e.py::test_case_{n:02d} PASSED{' ' * 30}[{n:3d}%]\n"
        for n in range(30)
    )
    return (
        passed
        + "=================================== FAILURES ===================================\n"
        + "___________________ test_get_concerts_list_default_pagination ___________________\n"
        + "tests/e2e/test_api_e2e.py:58: in test_get_concerts_list_default_pagination\n"
        + "    assert body[\"page_size\"] == 20\n"
        + e_line + "\n"
        + "=========================== short test summary info ============================\n"
        + "FAILED tests/e2e/test_api_e2e.py::test_get_concerts_list_default_pagination\n"
        + "========================= 1 failed, 30 passed in 2.10s =========================\n"
    )


def test_a_long_assertion_line_is_capped_and_the_rest_kept():
    dump = "E   assert 10 == 20" + " +  where ".join(["{'id': 1, 'city': 'Lyon'}"] * 200)
    excerpt = qa._failure_excerpt(_output(dump))

    reason, summary = excerpt.splitlines()
    assert reason.startswith("E   assert 10 == 20") and len(reason) <= qa._EXCERPT_LINE_CHARS + 1
    assert summary.startswith("FAILED tests/e2e/test_api_e2e.py::test_get_concerts_list_default_pagination")


def test_the_reason_survives_a_long_passing_prologue():
    output = ("tests/e2e/test_api_e2e.py::test_x PASSED\n" * 400) + _output("E   assert 10 == 20")

    assert "E   assert 10 == 20" in qa._failure_excerpt(output)


async def test_the_e2e_run_keeps_its_whole_output():
    claude = MagicMock()
    claude.run_tests = AsyncMock(return_value={"output": _output("E   assert 10 == 20"), "passed": False})

    await qa._pytest_e2e(claude, "/ws", "/ws/.venv-swarm/bin/python", "/ws/tests/e2e/test_api_e2e.py")

    assert claude.run_tests.await_args.kwargs["tail_chars"] >= qa.E2E_OUTPUT_TAIL_CHARS >= 50_000


async def test_run_tests_keeps_the_tail_it_is_asked_for(tmp_path):
    from theswarm.tools.claude import ClaudeCLI

    command = ["python", "-c", "print('R' * 12000 + 'END')"]

    default = await ClaudeCLI().run_tests(str(tmp_path), command, timeout=10)
    longer = await ClaudeCLI().run_tests(str(tmp_path), command, timeout=10, tail_chars=20_000)

    assert len(default["output"]) == 5000 and default["output"].rstrip().endswith("END")
    assert len(longer["output"].rstrip()) == 12003
