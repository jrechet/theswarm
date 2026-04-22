"""Tests for domain/memory — 100% coverage target."""

from __future__ import annotations

from theswarm.domain.memory.entities import MemoryEntry, Retrospective
from theswarm.domain.memory.value_objects import (
    MemoryCategory,
    ProjectScope,
    ScopeLayer,
)


class TestMemoryCategory:
    def test_all_values(self):
        assert MemoryCategory.STACK == "stack"
        assert MemoryCategory.CONVENTIONS == "conventions"
        assert MemoryCategory.ERRORS == "errors"
        assert MemoryCategory.ARCHITECTURE == "architecture"
        assert MemoryCategory.IMPROVEMENTS == "improvements"
        assert MemoryCategory.CROSS_PROJECT == "cross_project"


class TestProjectScope:
    def test_global(self):
        s = ProjectScope()
        assert s.is_global is True
        assert str(s) == "global"

    def test_project(self):
        s = ProjectScope(project_id="my-app")
        assert s.is_global is False
        assert str(s) == "my-app"


class TestMemoryEntry:
    def test_creation(self):
        e = MemoryEntry(
            category=MemoryCategory.STACK,
            content="Uses FastAPI with SQLAlchemy",
            agent="dev",
        )
        assert e.category == MemoryCategory.STACK
        assert e.scope.is_global is True

    def test_to_dict(self):
        e = MemoryEntry(
            category=MemoryCategory.ERRORS,
            content="Don't use print()",
            agent="qa",
            scope=ProjectScope("my-app"),
            cycle_date="2026-04-12",
        )
        d = e.to_dict()
        assert d["category"] == "errors"
        assert d["content"] == "Don't use print()"
        assert d["agent"] == "qa"
        assert d["project_id"] == "my-app"
        assert d["cycle_date"] == "2026-04-12"
        assert "created_at" in d

    def test_from_dict(self):
        d = {
            "category": "stack",
            "content": "Uses pytest",
            "agent": "qa",
            "project_id": "p1",
            "cycle_date": "2026-04-12",
            "created_at": "2026-04-12T10:00:00+00:00",
        }
        e = MemoryEntry.from_dict(d)
        assert e.category == MemoryCategory.STACK
        assert e.content == "Uses pytest"
        assert e.scope.project_id == "p1"

    def test_from_dict_minimal(self):
        d = {"category": "errors", "content": "x"}
        e = MemoryEntry.from_dict(d)
        assert e.agent == ""
        assert e.scope.is_global is True

    def test_promote_to_global(self):
        e = MemoryEntry(
            category=MemoryCategory.CONVENTIONS,
            content="Always use type hints",
            agent="dev",
            scope=ProjectScope("my-app"),
        )
        g = e.promote_to_global()
        assert g.category == MemoryCategory.CROSS_PROJECT
        assert g.scope.is_global is True
        assert g.content == "Always use type hints"


class TestMemoryScopeLayers:
    def test_global_scope_inferred(self):
        e = MemoryEntry(category=MemoryCategory.STACK, content="c")
        assert e.scope_layer == ScopeLayer.GLOBAL

    def test_project_scope_inferred(self):
        e = MemoryEntry(
            category=MemoryCategory.STACK, content="c",
            scope=ProjectScope("p1"),
        )
        assert e.scope_layer == ScopeLayer.PROJECT

    def test_role_project_scope_inferred(self):
        e = MemoryEntry(
            category=MemoryCategory.STACK, content="c",
            scope=ProjectScope("p1"),
            role="dev",
        )
        assert e.scope_layer == ScopeLayer.ROLE_PROJECT

    def test_agent_backfilled_from_codename(self):
        e = MemoryEntry(
            category=MemoryCategory.STACK, content="c",
            codename="Aarav", role="dev",
        )
        assert e.agent == "Aarav"

    def test_agent_backfilled_from_role_when_no_codename(self):
        e = MemoryEntry(category=MemoryCategory.STACK, content="c", role="po")
        assert e.agent == "po"

    def test_to_dict_contains_new_fields(self):
        e = MemoryEntry(
            category=MemoryCategory.STACK, content="c",
            scope=ProjectScope("p1"),
            codename="Mei", role="po",
        )
        d = e.to_dict()
        assert d["codename"] == "Mei"
        assert d["role"] == "po"
        assert d["scope_layer"] == "role_project"

    def test_from_dict_roundtrip_with_new_fields(self):
        d = {
            "category": "stack", "content": "c",
            "codename": "Kenji", "role": "dev",
            "project_id": "p1", "scope_layer": "role_project",
            "created_at": "2026-04-12T10:00:00+00:00",
        }
        e = MemoryEntry.from_dict(d)
        assert e.codename == "Kenji"
        assert e.role == "dev"
        assert e.scope_layer == ScopeLayer.ROLE_PROJECT


class TestRetrospective:
    def test_creation(self):
        entries = (
            MemoryEntry(category=MemoryCategory.STACK, content="a", agent="dev"),
            MemoryEntry(category=MemoryCategory.ERRORS, content="b", agent="qa"),
        )
        r = Retrospective(cycle_date="2026-04-12", project_id="p1", entries=entries)
        assert r.count == 2

    def test_empty(self):
        r = Retrospective(cycle_date="2026-04-12", project_id="p1")
        assert r.count == 0
