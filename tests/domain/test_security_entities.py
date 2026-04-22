"""Phase I domain tests — Security entities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from theswarm.domain.security.entities import (
    AuthZRule,
    DataInventoryEntry,
    SBOMArtifact,
    SecurityFinding,
    ThreatModel,
)
from theswarm.domain.security.value_objects import (
    AuthZEffect,
    DataClass,
    FindingSeverity,
    FindingStatus,
)


class TestThreatModel:
    def test_fresh_is_not_stale(self):
        tm = ThreatModel(
            id="t1", project_id="p", title="model",
            updated_at=datetime.now(timezone.utc),
        )
        assert tm.is_stale is False
        assert tm.freshness_days == 0

    def test_old_is_stale(self):
        tm = ThreatModel(
            id="t1", project_id="p", title="model",
            updated_at=datetime.now(timezone.utc) - timedelta(days=120),
        )
        assert tm.is_stale is True
        assert tm.freshness_days >= 120


class TestDataInventoryEntry:
    def test_sensitive_tiers(self):
        for cls in (DataClass.PII, DataClass.PAYMENT, DataClass.HEALTH,
                   DataClass.CONFIDENTIAL):
            e = DataInventoryEntry(
                id="d", project_id="p", field_name="x", classification=cls,
            )
            assert e.is_sensitive is True

    def test_non_sensitive_tiers(self):
        for cls in (DataClass.PUBLIC, DataClass.INTERNAL):
            e = DataInventoryEntry(
                id="d", project_id="p", field_name="x", classification=cls,
            )
            assert e.is_sensitive is False


class TestSecurityFinding:
    def test_sla_deadline_critical_is_24h(self):
        created = datetime(2026, 1, 1, tzinfo=timezone.utc)
        f = SecurityFinding(
            id="f1", project_id="p",
            severity=FindingSeverity.CRITICAL, title="bad", created_at=created,
        )
        assert f.sla_deadline == created + timedelta(hours=24)

    def test_is_open_covers_open_and_triaged(self):
        f_open = SecurityFinding(
            id="f", project_id="p", severity=FindingSeverity.HIGH,
            title="", status=FindingStatus.OPEN,
        )
        f_tri = SecurityFinding(
            id="f", project_id="p", severity=FindingSeverity.HIGH,
            title="", status=FindingStatus.TRIAGED,
        )
        f_res = SecurityFinding(
            id="f", project_id="p", severity=FindingSeverity.HIGH,
            title="", status=FindingStatus.RESOLVED,
        )
        assert f_open.is_open
        assert f_tri.is_open
        assert not f_res.is_open

    def test_is_breaching_sla(self):
        # 2 days ago, critical (24h SLA) → breaching
        f = SecurityFinding(
            id="f", project_id="p",
            severity=FindingSeverity.CRITICAL, title="",
            created_at=datetime.now(timezone.utc) - timedelta(days=2),
        )
        assert f.is_breaching_sla is True

    def test_resolved_never_breaches_sla(self):
        f = SecurityFinding(
            id="f", project_id="p",
            severity=FindingSeverity.CRITICAL, title="",
            status=FindingStatus.RESOLVED,
            created_at=datetime.now(timezone.utc) - timedelta(days=10),
        )
        assert f.is_breaching_sla is False


class TestAuthZRule:
    def test_key_tuple(self):
        r = AuthZRule(
            id="r", project_id="p", actor_role="admin",
            resource="/users", action="read", effect=AuthZEffect.ALLOW,
        )
        assert r.key == ("p", "admin", "/users", "read")


class TestSBOMArtifact:
    def test_defaults(self):
        a = SBOMArtifact(id="a", project_id="p")
        assert a.tool == "syft"
        assert a.package_count == 0
