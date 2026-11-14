"""The steps that are not a Claude call say what they do (A1).

Only Claude's own messages reached the theater: an install, a test run, a
push, five minutes of waiting for CI or a demo being filmed were silence,
and silence read as "stuck" ("je n'arrive pas à savoir où ça en est, si
c'est bloqué", the owner, 2026-11-11). Each of these steps now says one
line through the role's own channel (`ClaudeCLI.on_event`) — the theater's
feed, the home's live line and the watchdog's heartbeat all hear it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from theswarm.agents.base import say


class _Heard:
    def __init__(self) -> None:
        self.lines: list[str] = []

    async def on_event(self, text: str) -> None:
        self.lines.append(text)

    async def run_tests(self, workdir, command, *, timeout=300):
        return {"passed": True, "output": "1 passed", "exit_code": 0}


async def test_say_goes_through_the_role_s_channel_and_never_raises():
    heard = _Heard()
    await say({"claude": heard}, "Pushing feat/issue-12")
    assert heard.lines == ["Pushing feat/issue-12"]

    async def broken(text):
        raise RuntimeError("bridge down")

    await say({"claude": SimpleNamespace(on_event=broken)}, "anything")  # a step never fails on its words
    await say({}, "nobody listens")  # stub mode, the CLI: nothing to say it to
    await say({"claude": SimpleNamespace(on_event=None)}, "nobody listens")


async def test_the_dev_s_gate_says_it_installs_then_runs_the_tests(tmp_path):
    from theswarm.agents.dev import run_quality_gates

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_thing.py").write_text("def test_x(): pass\n")
    (tmp_path / "thing.py").write_text("x = 1\n")
    heard = _Heard()
    with patch("theswarm.tools.git.changed_files", new=AsyncMock(return_value=["thing.py"])):
        await run_quality_gates({"task": {"number": 1}, "workspace": str(tmp_path), "claude": heard})
    assert any("dependencies" in line for line in heard.lines)
    assert any("Running 1 test file" in line for line in heard.lines)
    assert any("Tests passed" in line for line in heard.lines)


async def test_the_ci_wait_says_it_waits_and_how_it_ended():
    from theswarm.agents import techlead
    from theswarm.agents.ci_gate import CiVerdict

    heard: list[str] = []

    async def tell(text):
        heard.append(text)

    with patch("theswarm.agents.ci_gate.wait_for_ci", new=AsyncMock(return_value=CiVerdict(state="green"))):
        state = await techlead._ci_gate_before_merge(object(), 851, "feat/x", {"head_sha": "abc"}, wait_seconds=300, tell=tell)
    assert state == "green"
    assert heard[0].startswith("Waiting for CI on PR #851") and "green" in heard[-1]


async def test_each_qa_step_says_what_it_starts():
    from theswarm.agents.base import speaking

    heard = _Heard()

    async def node(state):
        return {"done": True}

    wrapped = speaking("Running the unit tests", node)
    assert await wrapped({"claude": heard}) == {"done": True}
    assert heard.lines == ["Running the unit tests"] and wrapped.__name__ == "node"


def test_the_qa_graph_names_every_step():
    from theswarm.agents.qa import QA_STEP_WORDS, build_qa_graph

    nodes = set(build_qa_graph().nodes) - {"load_context", "__start__"}
    assert nodes <= set(QA_STEP_WORDS) and all(QA_STEP_WORDS[n] for n in nodes)
