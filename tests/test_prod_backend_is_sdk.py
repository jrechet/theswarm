"""Prod runs the Agent SDK backend explicitly (V2 runtime, M1).

`auto` stays CLI-first until three harness cycles have passed on the SDK;
prod opts in through docker-compose.yml, which is code, deployed with the
stack — the rollback is one line back to `cli` (invariant I13).
"""

from __future__ import annotations

from pathlib import Path

import yaml

COMPOSE = yaml.safe_load(Path("docker-compose.yml").read_text())


def test_the_service_runs_on_the_sdk_backend():
    env = COMPOSE["services"]["theswarm"]["environment"]
    assert "SWARM_CLAUDE_BACKEND=sdk" in env
