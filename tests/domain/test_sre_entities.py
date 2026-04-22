"""Phase I domain tests — SRE entities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from theswarm.domain.sre.entities import (
    CostSample,
    Deployment,
    Incident,
)
from theswarm.domain.sre.value_objects import (
    CostSource,
    DeployStatus,
    IncidentSeverity,
    IncidentStatus,
)


class TestDeployment:
    def test_is_terminal_for_terminal_states(self):
        for st in (DeployStatus.SUCCESS, DeployStatus.FAILED,
                   DeployStatus.ROLLED_BACK):
            d = Deployment(id="d", project_id="p", status=st)
            assert d.is_terminal

    def test_is_not_terminal_for_in_flight(self):
        for st in (DeployStatus.PENDING, DeployStatus.IN_PROGRESS):
            d = Deployment(id="d", project_id="p", status=st)
            assert not d.is_terminal

    def test_duration_seconds(self):
        start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(minutes=5)
        d = Deployment(
            id="d", project_id="p", status=DeployStatus.SUCCESS,
            started_at=start, completed_at=end,
        )
        assert d.duration_seconds == 300.0

    def test_duration_zero_when_incomplete(self):
        d = Deployment(id="d", project_id="p", status=DeployStatus.IN_PROGRESS)
        assert d.duration_seconds == 0.0


class TestIncident:
    def test_is_open_covers_open_triaged_mitigated(self):
        assert Incident(
            id="i", project_id="p", title="", severity=IncidentSeverity.SEV2,
            status=IncidentStatus.OPEN,
        ).is_open
        assert Incident(
            id="i", project_id="p", title="", severity=IncidentSeverity.SEV2,
            status=IncidentStatus.TRIAGED,
        ).is_open
        # mitigated is NOT is_open — mitigation stops paging, not the incident
        assert not Incident(
            id="i", project_id="p", title="", severity=IncidentSeverity.SEV2,
            status=IncidentStatus.MITIGATED,
        ).is_open
        assert not Incident(
            id="i", project_id="p", title="", severity=IncidentSeverity.SEV2,
            status=IncidentStatus.RESOLVED,
        ).is_open

    def test_mttr_and_mttm(self):
        detected = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mitigated = detected + timedelta(minutes=10)
        resolved = detected + timedelta(minutes=30)
        i = Incident(
            id="i", project_id="p", title="",
            severity=IncidentSeverity.SEV1,
            detected_at=detected, mitigated_at=mitigated, resolved_at=resolved,
        )
        assert i.mttm_seconds == 600.0
        assert i.mttr_seconds == 1800.0

    def test_mttr_zero_when_unresolved(self):
        i = Incident(
            id="i", project_id="p", title="",
            severity=IncidentSeverity.SEV2, status=IncidentStatus.OPEN,
        )
        assert i.mttr_seconds == 0.0
        assert i.mttm_seconds == 0.0


class TestCostSample:
    def test_defaults(self):
        s = CostSample(
            id="c", project_id="p", source=CostSource.AI, amount_usd=1.23,
        )
        assert s.window == "daily"
