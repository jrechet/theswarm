"""The target clones live on a volume, so a resumed cycle finds its tree.

Cycle 747bb89eced2 (2026-09-23) was resumed after a forced redeploy, but
~/.swarm-workspaces was inside the container: the continuation re-cloned
and redid the interrupted Dev iteration from scratch.
"""

from __future__ import annotations

import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
WORKSPACES = "/home/botuser/.swarm-workspaces"


def _service() -> dict:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    return compose, compose["services"]["theswarm"]


def test_the_workspaces_are_mounted_on_a_named_volume():
    compose, service = _service()
    mounts = {m.split(":")[1]: m.split(":")[0] for m in service["volumes"]}

    assert WORKSPACES in mounts
    source = mounts[WORKSPACES]
    assert not source.startswith("/"), "a host path needs preparing on the box; a named volume does not"
    assert source in compose.get("volumes", {})


def test_the_image_creates_the_mount_point_for_botuser():
    """An empty named volume takes the ownership of the image directory it
    is mounted over; without it the volume is root's and the clone fails."""
    dockerfile = (ROOT / "Dockerfile").read_text()
    run = dockerfile[dockerfile.index("useradd -m -s /bin/bash botuser"):]
    run = run[: run.index("\n\n")]

    assert WORKSPACES in run
    assert "chown -R botuser:botuser" in run and "/home/botuser" in run


def test_the_workspace_root_is_the_mounted_one():
    from theswarm.config import CycleConfig

    config = CycleConfig(github_repo="jrechet/concert-tour-app")
    assert config.workspace_dir.startswith(str(pathlib.Path.home() / ".swarm-workspaces"))
