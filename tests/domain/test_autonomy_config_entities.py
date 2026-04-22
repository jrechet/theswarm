"""Phase L domain tests — autonomy-spectrum config."""

from __future__ import annotations

from theswarm.domain.autonomy_config.entities import AutonomyConfig
from theswarm.domain.autonomy_config.value_objects import AutonomyLevel


class TestAutonomyLevel:
    def test_rank_is_monotonic(self):
        assert AutonomyLevel.MANUAL.rank < AutonomyLevel.ASSISTED.rank
        assert AutonomyLevel.ASSISTED.rank < AutonomyLevel.SUPERVISED.rank
        assert AutonomyLevel.SUPERVISED.rank < AutonomyLevel.AUTONOMOUS.rank

    def test_manual_and_assisted_require_human(self):
        assert AutonomyLevel.MANUAL.requires_human_before_action
        assert AutonomyLevel.ASSISTED.requires_human_before_action

    def test_supervised_and_autonomous_do_not_require_human(self):
        assert not AutonomyLevel.SUPERVISED.requires_human_before_action
        assert not AutonomyLevel.AUTONOMOUS.requires_human_before_action

    def test_string_values(self):
        assert AutonomyLevel.MANUAL.value == "manual"
        assert AutonomyLevel.AUTONOMOUS.value == "autonomous"


class TestAutonomyConfig:
    def test_default_level_is_supervised(self):
        c = AutonomyConfig(id="c1", project_id="p1", role="dev")
        assert c.level == AutonomyLevel.SUPERVISED

    def test_gate_label_maps_to_level(self):
        c_manual = AutonomyConfig(
            id="c1", project_id="p", role="dev", level=AutonomyLevel.MANUAL,
        )
        c_auto = AutonomyConfig(
            id="c2", project_id="p", role="dev",
            level=AutonomyLevel.AUTONOMOUS,
        )
        assert c_manual.gate_label == "human-initiated"
        assert c_auto.gate_label == "ship unless blocked"

    def test_frozen_dataclass(self):
        c = AutonomyConfig(id="c1", project_id="p", role="dev")
        import dataclasses
        try:
            c.level = AutonomyLevel.MANUAL  # type: ignore
        except dataclasses.FrozenInstanceError:
            return
        raise AssertionError("AutonomyConfig must be frozen")
