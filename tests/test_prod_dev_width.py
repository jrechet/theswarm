"""Prod runs two Dev tasks side by side (V2 M5b, plan section 8).

The default stayed 1 until three cycles were green at width 2; the compose
file is where prod takes it from, and 1 is the way back.
"""

from __future__ import annotations

import pathlib

import yaml


def test_prod_runs_two_dev_tasks_side_by_side():
    compose = yaml.safe_load(pathlib.Path("docker-compose.yml").read_text())
    env = compose["services"]["theswarm"]["environment"]

    assert "SWARM_DEV_PARALLELISM=2" in env


def test_the_code_default_is_still_the_single_path(monkeypatch):
    from theswarm.tools.git import dev_parallelism

    monkeypatch.delenv("SWARM_DEV_PARALLELISM", raising=False)
    assert dev_parallelism() == 1
