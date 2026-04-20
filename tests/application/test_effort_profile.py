"""Tests for Sprint B C2 — EffortProfile.apply."""

from __future__ import annotations

import pytest

from theswarm.application.services.effort_profile import EffortProfile
from theswarm.domain.projects.entities import ProjectConfig


class TestEffortProfile:
    def test_low_preset(self):
        resolved = EffortProfile.apply(ProjectConfig(effort="low", models={}))
        assert resolved.models == {"po": "haiku", "techlead": "haiku", "dev": "haiku", "qa": "haiku"}
        assert resolved.max_retries == 1
        assert resolved.thinking_budget == 0

    def test_medium_preset(self):
        resolved = EffortProfile.apply(ProjectConfig(effort="medium", models={}))
        assert resolved.models["dev"] == "sonnet"
        assert resolved.models["qa"] == "haiku"
        assert resolved.max_retries == 2
        assert resolved.thinking_budget == 2000

    def test_high_preset(self):
        resolved = EffortProfile.apply(ProjectConfig(effort="high", models={}))
        assert resolved.models["po"] == "opus"
        assert resolved.models["qa"] == "sonnet"
        assert resolved.max_retries == 5
        assert resolved.thinking_budget == 10_000

    def test_explicit_override_wins(self):
        config = ProjectConfig(
            effort="low",
            models={"dev": "opus"},
        )
        resolved = EffortProfile.apply(config)
        assert resolved.models["dev"] == "opus"
        assert resolved.models["po"] == "haiku"
        # Preset retries stay
        assert resolved.max_retries == 1

    def test_empty_model_value_does_not_override(self):
        config = ProjectConfig(effort="medium", models={"dev": ""})
        resolved = EffortProfile.apply(config)
        assert resolved.models["dev"] == "sonnet"

    def test_unknown_phase_in_models_ignored(self):
        config = ProjectConfig(effort="medium", models={"bogus": "claude-99"})
        resolved = EffortProfile.apply(config)
        assert "bogus" not in resolved.models
