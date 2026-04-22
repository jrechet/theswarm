"""Phase L domain tests — refactor programs."""

from __future__ import annotations

from theswarm.domain.refactor_programs.entities import RefactorProgram
from theswarm.domain.refactor_programs.value_objects import (
    RefactorProgramStatus,
)


class TestRefactorProgram:
    def test_active_is_active(self):
        p = RefactorProgram(
            id="p1", title="x", status=RefactorProgramStatus.ACTIVE,
        )
        assert p.is_active
        assert not p.is_terminal

    def test_proposed_not_active(self):
        p = RefactorProgram(id="p1", title="x")
        assert p.status == RefactorProgramStatus.PROPOSED
        assert not p.is_active
        assert not p.is_terminal

    def test_completed_is_terminal(self):
        p = RefactorProgram(
            id="p1", title="x", status=RefactorProgramStatus.COMPLETED,
        )
        assert p.is_terminal

    def test_cancelled_is_terminal(self):
        p = RefactorProgram(
            id="p1", title="x", status=RefactorProgramStatus.CANCELLED,
        )
        assert p.is_terminal

    def test_project_count(self):
        p = RefactorProgram(
            id="p1", title="x",
            target_projects=("a", "b", "c"),
        )
        assert p.project_count == 3

    def test_empty_project_count(self):
        p = RefactorProgram(id="p1", title="x")
        assert p.project_count == 0
