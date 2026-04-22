"""Phase L domain tests — prompt library."""

from __future__ import annotations

from datetime import datetime, timezone

from theswarm.domain.prompt_library.entities import (
    PromptAuditEntry,
    PromptTemplate,
)
from theswarm.domain.prompt_library.value_objects import PromptAuditAction


class TestPromptTemplate:
    def test_defaults_active(self):
        t = PromptTemplate(id="t1", name="po.morning")
        assert t.is_active is True

    def test_deprecated_not_active(self):
        t = PromptTemplate(id="t1", name="po.morning", deprecated=True)
        assert t.is_active is False

    def test_stores_body_role_and_version(self):
        t = PromptTemplate(
            id="t1", name="po.morning", role="po",
            body="hello", version=3,
        )
        assert t.role == "po"
        assert t.body == "hello"
        assert t.version == 3

    def test_frozen_dataclass(self):
        t = PromptTemplate(id="t1", name="po.morning")
        import dataclasses
        try:
            t.version = 99  # type: ignore
        except dataclasses.FrozenInstanceError:
            return
        raise AssertionError("PromptTemplate must be frozen")


class TestPromptAuditEntry:
    def test_create_action(self):
        e = PromptAuditEntry(
            id="a1", prompt_name="x", action=PromptAuditAction.CREATE,
            after_version=1,
        )
        assert e.action == PromptAuditAction.CREATE

    def test_is_version_bump_true_when_after_greater(self):
        e = PromptAuditEntry(
            id="a1", prompt_name="x", action=PromptAuditAction.UPDATE,
            before_version=1, after_version=2,
        )
        assert e.is_version_bump

    def test_is_version_bump_false_when_equal(self):
        e = PromptAuditEntry(
            id="a1", prompt_name="x", action=PromptAuditAction.DEPRECATE,
            before_version=2, after_version=2,
        )
        assert not e.is_version_bump

    def test_default_created_at_is_utc(self):
        e = PromptAuditEntry(
            id="a1", prompt_name="x", action=PromptAuditAction.CREATE,
        )
        assert isinstance(e.created_at, datetime)
        assert e.created_at.tzinfo == timezone.utc


class TestPromptAuditAction:
    def test_action_values(self):
        assert PromptAuditAction.CREATE.value == "create"
        assert PromptAuditAction.UPDATE.value == "update"
        assert PromptAuditAction.DEPRECATE.value == "deprecate"
        assert PromptAuditAction.RESTORE.value == "restore"
