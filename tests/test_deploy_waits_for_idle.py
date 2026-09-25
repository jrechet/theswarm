"""A deploy waits for the running cycle, bounded (V2 M4, the ops side).

The resume brings an interrupted cycle back once, but the node in flight
is lost and a second deploy loses the cycle. A merge made while prod was
idle deployed ten minutes later into 2f5114ae7713 (2026-09-25).
"""

from __future__ import annotations

import json
import pathlib
import re
import subprocess

import yaml

CD = pathlib.Path(".github/workflows/cd.yml")


def _deploy_job() -> dict:
    return yaml.safe_load(CD.read_text())["jobs"]["deploy"]


def _wait_step() -> dict:
    return next(s for s in _deploy_job()["steps"] if s.get("name") == "Wait for running cycles")


def test_the_wait_comes_before_the_deploy():
    names = [s.get("name") for s in _deploy_job()["steps"]]

    assert names.index("Wait for running cycles") < names.index("Deploy")


def test_the_job_has_room_for_the_wait_and_the_deploy():
    wait = int(_wait_step()["env"]["MAX_WAIT_SECONDS"])

    assert _deploy_job()["timeout-minutes"] * 60 >= wait + 15 * 60


def _run(body: str, max_wait: int = 0) -> subprocess.CompletedProcess:
    """The step's script, against a fake curl that answers `body`."""
    script = _wait_step()["run"]
    fake = f'curl() {{ printf %s {json.dumps(body)}; }}\nsleep() {{ :; }}\n'
    env = {"SWARM_ACCESS_KEY": "k", "SWARM_BASE": "http://x", "MAX_WAIT_SECONDS": str(max_wait), "PATH": "/usr/bin:/bin"}
    return subprocess.run(["bash", "-c", fake + script], capture_output=True, text=True, env=env, timeout=30)


def test_an_idle_service_deploys_at_once():
    body = json.dumps({"cycles": [{"id": "a", "status": "completed"}]}, separators=(",", ":"))

    out = _run(body)

    assert "No cycle running" in out.stdout


def test_a_running_cycle_is_waited_for_then_deployed_past_the_bound():
    body = json.dumps({"cycles": [{"id": "a", "status": "running"}]}, separators=(",", ":"))

    out = _run(body, max_wait=0)

    assert "::warning::A cycle is still running" in out.stdout


def test_an_api_that_does_not_answer_never_blocks():
    out = _run("404 page not found")

    assert "No cycle running" in out.stdout


def test_both_json_spacings_are_read():
    pattern = re.compile(r'"status": ?"(running|queued)"')
    assert pattern.search('{"status":"running"}') and pattern.search('{"status": "queued"}')
