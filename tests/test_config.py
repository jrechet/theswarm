"""Tests for theswarm.config — configuration and base types."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from theswarm.config import CycleConfig, Phase, Role


# ── Role enum ──────────────────────────────────────────────────────────


def test_role_values():
    assert Role.PO.value == "po"
    assert Role.TECHLEAD.value == "techlead"
    assert Role.DEV.value == "dev"
    assert Role.QA.value == "qa"


def test_role_is_str():
    assert isinstance(Role.PO, str)
    assert Role.DEV == "dev"


# ── Phase enum ─────────────────────────────────────────────────────────


def test_phase_values():
    assert Phase.MORNING.value == "morning"
    assert Phase.DEVELOPMENT.value == "development"
    assert Phase.DEMO.value == "demo"
    assert Phase.EVENING.value == "evening"


# ── CycleConfig defaults ──────────────────────────────────────────────


def test_cycle_config_defaults():
    cfg = CycleConfig(github_repo="owner/repo")
    assert cfg.team_id == "alpha"
    assert cfg.claude_model == "sonnet"
    assert cfg.github_repo == "owner/repo"


def test_cycle_config_is_real_mode_true():
    cfg = CycleConfig(github_repo="owner/repo")
    assert cfg.is_real_mode is True


def test_cycle_config_is_real_mode_false():
    cfg = CycleConfig(github_repo="")
    assert cfg.is_real_mode is False


def test_cycle_config_repo_clone_url():
    cfg = CycleConfig(github_repo="owner/repo")
    assert cfg.repo_clone_url == "https://github.com/owner/repo.git"


def test_cycle_config_repo_clone_url_empty():
    cfg = CycleConfig(github_repo="")
    assert cfg.repo_clone_url == ""


def test_cycle_config_auto_workspace_dir():
    cfg = CycleConfig(github_repo="owner/my-repo")
    expected_suffix = os.path.join(".swarm-workspaces", "alpha", "my-repo")
    assert cfg.workspace_dir.endswith(expected_suffix)


def test_cycle_config_explicit_workspace_dir():
    cfg = CycleConfig(github_repo="owner/repo", workspace_dir="/custom/path")
    assert cfg.workspace_dir == "/custom/path"


def test_cycle_config_token_budget():
    cfg = CycleConfig(github_repo="owner/repo")
    assert Role.DEV in cfg.token_budget
    assert cfg.token_budget[Role.DEV] == 1_000_000


# ── CycleConfig.from_env ──────────────────────────────────────────────


def test_from_env_with_vars():
    env = {
        "SWARM_GITHUB_REPO": "org/project",
        "SWARM_TEAM_ID": "beta",
        "SWARM_CLAUDE_MODEL": "opus",
        "SWARM_WORKSPACE_DIR": "/tmp/ws",
    }
    with patch.dict(os.environ, env, clear=False):
        cfg = CycleConfig.from_env()
    assert cfg.github_repo == "org/project"
    assert cfg.team_id == "beta"
    assert cfg.claude_model == "opus"
    assert cfg.workspace_dir == "/tmp/ws"


def test_from_env_defaults():
    env_clear = {
        "SWARM_GITHUB_REPO": "",
        "SWARM_TEAM_ID": "",
        "SWARM_CLAUDE_MODEL": "",
        "SWARM_WORKSPACE_DIR": "",
    }
    with patch.dict(os.environ, env_clear, clear=False):
        # Remove the keys entirely to test defaults
        for k in env_clear:
            os.environ.pop(k, None)
        cfg = CycleConfig.from_env()
    assert cfg.github_repo == ""
    assert cfg.team_id == "alpha"
    assert cfg.claude_model == "sonnet"
