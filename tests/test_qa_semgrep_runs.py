"""QA's OWASP scan runs even though semgrep is not in the image.

It failed "No such file or directory: 'semgrep'" on every prod cycle until
2026-09-25, and the report said not_run. It now runs through uv, pinned,
with telemetry off; SWARM_QA_SEMGREP=0 turns it off.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from theswarm.agents import qa


def _which(present: set[str]):
    return lambda name: f"/usr/local/bin/{name}" if name in present else None


def test_semgrep_on_path_is_used_as_is(monkeypatch):
    monkeypatch.setattr("shutil.which", _which({"semgrep", "uv"}))

    command = qa._semgrep_command()

    assert command[0] == "semgrep" and "--metrics=off" in command


def test_without_semgrep_uv_runs_the_pinned_version(monkeypatch):
    monkeypatch.setattr("shutil.which", _which({"uv"}))

    command = qa._semgrep_command()

    assert command[:5] == ["/usr/local/bin/uv", "tool", "run", "--from", f"semgrep=={qa.SEMGREP_VERSION}"]
    assert "--config=p/owasp-top-ten" in command and "--metrics=off" in command


def test_neither_means_not_run(monkeypatch):
    monkeypatch.setattr("shutil.which", _which(set()))

    assert qa._semgrep_command() is None


@pytest.mark.parametrize("value", ["0", "false", "no"])
def test_the_scan_can_be_turned_off(monkeypatch, value):
    monkeypatch.setattr("shutil.which", _which({"semgrep", "uv"}))
    monkeypatch.setenv("SWARM_QA_SEMGREP", value)

    assert qa._semgrep_command() is None


async def test_the_scan_gets_room_for_its_first_download(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", _which({"uv"}))
    claude = SimpleNamespace(run_tests=AsyncMock(return_value={"output": '{"results": []}', "passed": True}))

    out = await qa.run_security_scan({"claude": claude, "workspace": str(tmp_path)})

    assert claude.run_tests.await_args.kwargs["timeout"] == qa.SEMGREP_TIMEOUT_SECONDS
    assert out["security_scan"]["semgrep_status"] == "pass"


async def test_a_scan_that_cannot_run_says_not_run(monkeypatch, tmp_path):
    monkeypatch.setattr("shutil.which", _which(set()))
    claude = SimpleNamespace(run_tests=AsyncMock())

    out = await qa.run_security_scan({"claude": claude, "workspace": str(tmp_path)})

    assert out["security_scan"]["semgrep_status"] == "not_run"
    assert claude.run_tests.await_count == 0


def test_the_uv_cache_lives_on_the_data_volume():
    import pathlib

    import yaml

    compose = yaml.safe_load(pathlib.Path("docker-compose.yml").read_text())
    env = compose["services"]["theswarm"]["environment"]
    assert "UV_CACHE_DIR=/home/botuser/.swarm-data/uv-cache" in env
