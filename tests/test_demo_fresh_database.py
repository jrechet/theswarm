"""Each demo server can have a database of its own (`{tmp}` in `demo.env`).

The demo servers ran on the workspace's database, which outlives cycles:
QA's E2E runs leave tours behind, the seed saw a non-empty database and
stood aside, and the tour-revenue demo (03790f693195) showed tour 1 — an
E2E leftover — at "revenue 0.00, 0 concerts". A target now declares a
throwaway database per launch, and its seed writes into the one its server
reads.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

from theswarm.agents import qa

DECLARED = """\
demo:
  command: "{python} -m uvicorn src.main:app --host 127.0.0.1 --port {port}"
  env:
    DATABASE_URL: "sqlite:///{tmp}/demo.db"
    LABEL: "json {not a placeholder}"
  seed:
    - "{python} scripts/seed_demo.py"
"""


def test_the_declared_env_gets_the_launch_s_own_tmp(tmp_path):
    (tmp_path / "theswarm.yaml").write_text(DECLARED)

    _, first = qa._demo_launch(str(tmp_path), "/venv/bin/python", 9001)
    _, second = qa._demo_launch(str(tmp_path), "/venv/bin/python", 9002)

    assert first["DATABASE_URL"].startswith("sqlite:///") and first["DATABASE_URL"].endswith("/demo.db")
    assert os.path.isdir(first["DATABASE_URL"].removeprefix("sqlite:///").removesuffix("/demo.db"))
    assert first["DATABASE_URL"] != second["DATABASE_URL"]
    assert first["LABEL"] == "json {not a placeholder}"  # only the three names are filled


async def _walk(tmp_path, monkeypatch, launch_env: dict) -> dict:
    seen: dict = {}

    async def seed(workspace, commands, *, python, url, env):
        seen.update(env)
        return []

    class Recorder:
        async def screenshot(self, url, label):
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
    monkeypatch.setattr(qa, "_find_system_python", lambda ws: "python")
    monkeypatch.setattr(qa, "_run_demo_setup", AsyncMock())
    monkeypatch.setattr(qa, "_demo_launch", lambda ws, py, port: (["true"], launch_env))
    monkeypatch.setattr(qa, "_pages_to_capture", lambda ws, extra: [("", "homepage")])
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=Proc())), \
         patch("theswarm.infrastructure.resilience.wait_for_http_ready", AsyncMock()), \
         patch("theswarm.infrastructure.recording.playwright_recorder.PlaywrightRecorder", Recorder):
        await qa.capture_demo_screenshots({"workspace": str(tmp_path), "claude": object()})
    return seen


async def test_a_declared_target_is_seeded_in_its_server_s_database(tmp_path, monkeypatch):
    (tmp_path / "theswarm.yaml").write_text(DECLARED)

    seen = await _walk(tmp_path, monkeypatch, {"PATH": "/usr/bin", "DATABASE_URL": "sqlite:////t/1/demo.db"})

    assert seen["DATABASE_URL"] == "sqlite:////t/1/demo.db"


async def test_an_undeclared_target_is_seeded_in_the_scrubbed_environment(tmp_path, monkeypatch):
    (tmp_path / "theswarm.yaml").write_text("demo:\n  seed:\n    - \"true\"\n")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret")

    seen = await _walk(tmp_path, monkeypatch, dict(os.environ))

    assert "GITHUB_TOKEN" not in seen
