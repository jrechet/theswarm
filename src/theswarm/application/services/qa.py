"""Application services for the QA-enrichments bounded context (Phase F)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from theswarm.domain.qa.entities import (
    FlakeRecord,
    OutcomeCard,
    QualityGate,
    QuarantineEntry,
    StoryAcceptance,
    TestPlan,
)
from theswarm.domain.qa.value_objects import (
    GateName,
    GateStatus,
    QuarantineStatus,
    TestArchetype,
)
from theswarm.infrastructure.qa import (
    SQLiteFlakeRecordRepository,
    SQLiteOutcomeCardRepository,
    SQLiteQualityGateRepository,
    SQLiteQuarantineRepository,
    SQLiteTestPlanRepository,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ArchetypeMixService:
    """Record required vs. produced test archetypes per task.

    Tracks whether each story/task has the right *kinds* of tests
    (unit, integration, e2e, visual, a11y, perf, security), not just
    raw count or line coverage.
    """

    def __init__(self, repo: SQLiteTestPlanRepository) -> None:
        self._repo = repo

    async def set_required(
        self,
        *,
        project_id: str,
        task_id: str,
        required: tuple[TestArchetype, ...],
        notes: str = "",
    ) -> TestPlan:
        existing = await self._repo.get_for_task(project_id, task_id)
        plan = TestPlan(
            id=existing.id if existing else TestPlan.new_id(),
            project_id=project_id,
            task_id=task_id,
            required=required,
            produced=existing.produced if existing else (),
            notes=notes or (existing.notes if existing else ""),
            created_at=existing.created_at if existing else _now(),
            updated_at=_now(),
        )
        return await self._repo.upsert(plan)

    async def mark_produced(
        self,
        *,
        project_id: str,
        task_id: str,
        archetype: TestArchetype,
    ) -> TestPlan | None:
        existing = await self._repo.get_for_task(project_id, task_id)
        if existing is None:
            return None
        if archetype in existing.produced:
            return existing
        plan = replace(
            existing,
            produced=tuple([*existing.produced, archetype]),
            updated_at=_now(),
        )
        return await self._repo.upsert(plan)

    async def get(self, project_id: str, task_id: str) -> TestPlan | None:
        return await self._repo.get_for_task(project_id, task_id)

    async def list(self, project_id: str) -> list[TestPlan]:
        return await self._repo.list_for_project(project_id)


class FlakeTrackerService:
    """Update running flake scores for individual tests.

    Each call to ``record_run`` bumps the counters for a single
    ``(project_id, test_id)`` pair; ``flake_score`` and
    ``should_quarantine`` are computed by the entity.
    """

    def __init__(self, repo: SQLiteFlakeRecordRepository) -> None:
        self._repo = repo

    async def record_run(
        self,
        *,
        project_id: str,
        test_id: str,
        failed: bool,
        failure_reason: str = "",
    ) -> FlakeRecord:
        existing = await self._repo.get_for_test(project_id, test_id)
        now = _now()
        if existing is None:
            record = FlakeRecord(
                id=FlakeRecord.new_id(),
                project_id=project_id,
                test_id=test_id,
                runs=1,
                failures=1 if failed else 0,
                last_failure_reason=failure_reason if failed else "",
                last_run_at=now,
                updated_at=now,
            )
        else:
            record = replace(
                existing,
                runs=existing.runs + 1,
                failures=existing.failures + (1 if failed else 0),
                last_failure_reason=(
                    failure_reason if failed else existing.last_failure_reason
                ),
                last_run_at=now,
                updated_at=now,
            )
        return await self._repo.upsert(record)

    async def list(self, project_id: str) -> list[FlakeRecord]:
        return await self._repo.list_for_project(project_id)

    async def get(self, project_id: str, test_id: str) -> FlakeRecord | None:
        return await self._repo.get_for_test(project_id, test_id)


class QuarantineService:
    """Manage the list of tests pulled out of the blocking suite."""

    def __init__(self, repo: SQLiteQuarantineRepository) -> None:
        self._repo = repo

    async def quarantine(
        self,
        *,
        project_id: str,
        test_id: str,
        reason: str = "",
    ) -> QuarantineEntry:
        entry = QuarantineEntry(
            id=QuarantineEntry.new_id(),
            project_id=project_id,
            test_id=test_id,
            reason=reason,
            status=QuarantineStatus.ACTIVE,
        )
        return await self._repo.add(entry)

    async def release(self, *, entry_id: str, reason: str = "") -> None:
        await self._repo.release(entry_id, reason=reason)

    async def list_active(self, project_id: str) -> list[QuarantineEntry]:
        return await self._repo.list_active(project_id)

    async def list_all(
        self, project_id: str, *, limit: int = 50,
    ) -> list[QuarantineEntry]:
        return await self._repo.list_for_project(project_id, limit=limit)


class QualityGateService:
    """Capture per-gate results (axe, lighthouse, k6, gitleaks, osv, sbom, license)."""

    def __init__(self, repo: SQLiteQualityGateRepository) -> None:
        self._repo = repo

    async def record(
        self,
        *,
        project_id: str,
        gate: GateName,
        status: GateStatus = GateStatus.UNKNOWN,
        summary: str = "",
        pr_url: str = "",
        task_id: str = "",
        score: float | None = None,
        finding_count: int = 0,
        details_json: str = "{}",
    ) -> QualityGate:
        entry = QualityGate(
            id=QualityGate.new_id(),
            project_id=project_id,
            gate=gate,
            status=status,
            summary=summary,
            pr_url=pr_url,
            task_id=task_id,
            score=score,
            finding_count=finding_count,
            details_json=details_json,
        )
        return await self._repo.add(entry)

    async def latest_snapshot(self, project_id: str) -> dict[GateName, QualityGate]:
        """Return the freshest gate result for each GateName in the project."""
        snapshot: dict[GateName, QualityGate] = {}
        for gate in GateName:
            latest = await self._repo.latest_for_gate(project_id, gate)
            if latest is not None:
                snapshot[gate] = latest
        return snapshot

    async def list(
        self, project_id: str, *, limit: int = 50,
    ) -> list[QualityGate]:
        return await self._repo.list_for_project(project_id, limit=limit)


class OutcomeCardService:
    """Build and list one-slide demo outcome cards for stories."""

    def __init__(self, repo: SQLiteOutcomeCardRepository) -> None:
        self._repo = repo

    async def create(
        self,
        *,
        project_id: str,
        story_id: str = "",
        title: str = "",
        acceptance: tuple[StoryAcceptance, ...] = (),
        metric_name: str = "",
        metric_before: str = "",
        metric_after: str = "",
        screenshot_path: str = "",
        narrated_video_path: str = "",
        summary: str = "",
    ) -> OutcomeCard:
        card = OutcomeCard(
            id=OutcomeCard.new_id(),
            project_id=project_id,
            story_id=story_id,
            title=title,
            acceptance=acceptance,
            metric_name=metric_name,
            metric_before=metric_before,
            metric_after=metric_after,
            screenshot_path=screenshot_path,
            narrated_video_path=narrated_video_path,
            summary=summary,
        )
        return await self._repo.add(card)

    async def get(self, card_id: str) -> OutcomeCard | None:
        return await self._repo.get(card_id)

    async def list(
        self, project_id: str, *, limit: int = 20,
    ) -> list[OutcomeCard]:
        return await self._repo.list_for_project(project_id, limit=limit)

    def make_acceptance(
        self, *, text: str, passed: bool = False, evidence: str = "",
    ) -> StoryAcceptance:
        return StoryAcceptance(text=text, passed=passed, evidence=evidence)
