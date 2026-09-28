"""The demo has data to show (`demo.seed`, seen in docs/demos/v2-play-to-demo.webm).

Cycle 28371c2016da built GET /api/v1/concerts/{id}/occupancy; QA walked
/api/v1/concerts/1/occupancy on its demo server, got a 404 — the demo's
database was empty — and skipped it. The screenshots showed an empty
dashboard, the report no page of the feature. A target now declares how
its demo gets data: `demo.seed` commands, run once the demo server
answers, with its URL, in the scrubbed environment.
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, patch

from theswarm.agents import qa
from theswarm.agents.qa_demo_seed import run_seed


async def test_each_command_runs_with_the_server_s_url(tmp_path):
    out = tmp_path / "seen.txt"
    commands = [
        f"{{python}} -c \"import os,sys; open('{out}','a').write(sys.argv[1]+' '+os.environ['DEMO_URL']+'\\n')\" {{url}}",
    ]

    outcomes = await run_seed(str(tmp_path), commands, python=sys.executable,
                              url="http://127.0.0.1:9001", env={"PATH": "/usr/bin:/bin"})

    assert out.read_text() == "http://127.0.0.1:9001 http://127.0.0.1:9001\n"
    assert outcomes == [(commands[0], 0)]


async def test_nothing_declared_runs_nothing(tmp_path):
    assert await run_seed(str(tmp_path), None, python="python", url="u", env={}) == []
    assert await run_seed(str(tmp_path), [], python="python", url="u", env={}) == []


async def test_a_failing_command_is_logged_and_the_next_runs(tmp_path, caplog):
    out = tmp_path / "second.txt"
    commands = ["exit 3", f"touch {out}"]

    outcomes = await run_seed(str(tmp_path), commands, python="python", url="u",
                              env={"PATH": "/usr/bin:/bin"})

    assert outcomes == [("exit 3", 3), (f"touch {out}", 0)]
    assert out.exists()
    assert "demo seed failed" in caplog.text


async def test_the_two_capture_lanes_never_seed_at_once(tmp_path):
    """Both lanes' servers write the same workspace database: a seed that
    checks "empty?" before writing must not race its twin."""
    log = tmp_path / "order.txt"
    command = (f"echo start >> {log}; sleep 0.3; echo end >> {log}")

    await asyncio.gather(
        run_seed(str(tmp_path), [command], python="python", url="a", env={"PATH": "/usr/bin:/bin"}),
        run_seed(str(tmp_path), [command], python="python", url="b", env={"PATH": "/usr/bin:/bin"}),
    )

    assert log.read_text().split() == ["start", "end", "start", "end"]


async def test_a_seed_that_hangs_is_cut_off(tmp_path, monkeypatch):
    from theswarm.agents import qa_demo_seed

    monkeypatch.setattr(qa_demo_seed, "DEMO_SEED_TIMEOUT_SECONDS", 0.2)

    outcomes = await run_seed(str(tmp_path), ["sleep 5"], python="python", url="u",
                              env={"PATH": "/usr/bin:/bin"})

    assert outcomes == [("sleep 5", None)]


async def test_the_screenshot_walk_seeds_before_it_walks(monkeypatch, tmp_path):
    (tmp_path / "theswarm.yaml").write_text(
        "demo:\n  seed:\n    - \"{python} scripts/seed_demo.py {url}\"\n",
    )
    calls: list[tuple] = []

    async def seed(workspace, commands, *, python, url, env):
        calls.append((workspace, tuple(commands), url, env.get("DEMO_URL")))
        return []

    class Recorder:
        async def screenshot(self, url, label):
            calls.append(("shot", label))
            return (label, b"png")

        async def close(self):
            pass

    class Proc:
        returncode = None

        def send_signal(self, sig):
            self.returncode = 0

        async def wait(self):
            return 0

    monkeypatch.setattr(qa, "run_seed", seed)
    monkeypatch.setattr(qa, "_page_status", AsyncMock(return_value=200))
    monkeypatch.setattr(qa, "e2e_port", lambda: 9998)
    monkeypatch.setattr(qa, "_find_system_python", lambda ws: "/venv/bin/python")
    monkeypatch.setattr(qa, "_run_demo_setup", AsyncMock())
    monkeypatch.setattr(qa, "_demo_launch", lambda ws, py, port: (["true"], {}))
    monkeypatch.setattr(qa, "_pages_to_capture", lambda ws, extra: [("", "homepage")])
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=Proc())), \
         patch("theswarm.infrastructure.resilience.wait_for_http_ready", AsyncMock()), \
         patch("theswarm.infrastructure.recording.playwright_recorder.PlaywrightRecorder", Recorder):
        await qa.capture_demo_screenshots({"workspace": str(tmp_path), "claude": object()})

    assert calls[0] == (str(tmp_path), ("{python} scripts/seed_demo.py {url}",),
                        "http://127.0.0.1:9999", None)
    assert calls[1] == ("shot", "homepage")
