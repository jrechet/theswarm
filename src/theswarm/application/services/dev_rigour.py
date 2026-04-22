"""Application services for the Dev-rigour bounded context (Phase E)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

from theswarm.domain.dev_rigour.entities import (
    CoverageDelta,
    DevThought,
    RefactorPreflight,
    SelfReview,
    SelfReviewFinding,
    TddArtifact,
)
from theswarm.domain.dev_rigour.value_objects import (
    FindingSeverity,
    PreflightDecision,
    TddPhase,
    ThoughtKind,
)
from theswarm.infrastructure.dev_rigour import (
    SQLiteCoverageDeltaRepository,
    SQLiteDevThoughtRepository,
    SQLiteRefactorPreflightRepository,
    SQLiteSelfReviewRepository,
    SQLiteTddArtifactRepository,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DevThoughtService:
    """Log exploration/research thoughts for a Dev agent.

    The dashboard surfaces these live so humans can follow the research
    trail rather than just seeing the final diff.
    """

    def __init__(self, repo: SQLiteDevThoughtRepository) -> None:
        self._repo = repo

    async def log(
        self,
        *,
        project_id: str,
        kind: ThoughtKind = ThoughtKind.NOTE,
        content: str = "",
        codename: str = "",
        task_id: str = "",
    ) -> DevThought:
        thought = DevThought(
            id=DevThought.new_id(),
            project_id=project_id,
            codename=codename,
            kind=kind,
            task_id=task_id,
            content=content.strip(),
        )
        return await self._repo.add(thought)

    async def recent(
        self, project_id: str, *, limit: int = 50,
    ) -> list[DevThought]:
        return await self._repo.list_for_project(project_id, limit=limit)

    async def for_task(self, task_id: str) -> list[DevThought]:
        return await self._repo.list_for_task(task_id)


class TddGateService:
    """Record the TDD red-green-refactor artifact for a task.

    Usage:
      * ``record_red(task_id, tests=[...], commit=sha)`` captures the failing run.
      * ``record_green(task_id, commit=sha)`` promotes it once the tests pass.

    A task has at most one artifact; ``upsert`` by ``(project_id, task_id)``
    keeps history simple — the repo itself is a running state machine.
    """

    def __init__(self, repo: SQLiteTddArtifactRepository) -> None:
        self._repo = repo

    async def record_red(
        self,
        *,
        project_id: str,
        task_id: str,
        test_files: tuple[str, ...] = (),
        commit: str = "",
        codename: str = "",
        notes: str = "",
    ) -> TddArtifact:
        existing = await self._repo.get_for_task(project_id, task_id)
        artifact = TddArtifact(
            id=existing.id if existing else TddArtifact.new_id(),
            project_id=project_id,
            task_id=task_id,
            codename=codename or (existing.codename if existing else ""),
            phase=TddPhase.RED,
            test_files=test_files or (existing.test_files if existing else ()),
            red_commit=commit or (existing.red_commit if existing else ""),
            green_commit=existing.green_commit if existing else "",
            notes=notes or (existing.notes if existing else ""),
            created_at=existing.created_at if existing else _now(),
            updated_at=_now(),
        )
        return await self._repo.upsert(artifact)

    async def record_green(
        self,
        *,
        project_id: str,
        task_id: str,
        commit: str = "",
        notes: str = "",
    ) -> TddArtifact | None:
        existing = await self._repo.get_for_task(project_id, task_id)
        if existing is None:
            return None
        artifact = replace(
            existing,
            phase=TddPhase.GREEN,
            green_commit=commit or existing.green_commit,
            notes=notes or existing.notes,
            updated_at=_now(),
        )
        return await self._repo.upsert(artifact)

    async def mark_refactor(
        self, *, project_id: str, task_id: str,
    ) -> TddArtifact | None:
        existing = await self._repo.get_for_task(project_id, task_id)
        if existing is None or existing.phase == TddPhase.RED:
            return None
        artifact = replace(
            existing, phase=TddPhase.REFACTOR, updated_at=_now(),
        )
        return await self._repo.upsert(artifact)

    async def list(self, project_id: str) -> list[TddArtifact]:
        return await self._repo.list_for_project(project_id)


class RefactorPreflightService:
    """Log pre-refactor checks on deletion-heavy diffs.

    ``threshold_lines`` is the minimum deletion size that triggers a
    preflight. Diffs smaller than the threshold are not logged — the
    service simply returns ``None`` so callers can short-circuit.
    """

    DEFAULT_THRESHOLD = 20

    def __init__(
        self,
        repo: SQLiteRefactorPreflightRepository,
        *,
        threshold_lines: int = DEFAULT_THRESHOLD,
    ) -> None:
        self._repo = repo
        self._threshold = threshold_lines

    @property
    def threshold_lines(self) -> int:
        return self._threshold

    async def evaluate(
        self,
        *,
        project_id: str,
        deletion_lines: int,
        files_touched: tuple[str, ...] = (),
        callers_checked: tuple[str, ...] = (),
        decision: PreflightDecision = PreflightDecision.PROCEED,
        reason: str = "",
        pr_url: str = "",
        task_id: str = "",
        codename: str = "",
    ) -> RefactorPreflight | None:
        if deletion_lines < self._threshold:
            return None
        preflight = RefactorPreflight(
            id=RefactorPreflight.new_id(),
            project_id=project_id,
            pr_url=pr_url,
            task_id=task_id,
            codename=codename,
            deletion_lines=deletion_lines,
            files_touched=files_touched,
            callers_checked=callers_checked,
            decision=decision,
            reason=reason,
        )
        return await self._repo.add(preflight)

    async def list(self, project_id: str) -> list[RefactorPreflight]:
        return await self._repo.list_for_project(project_id)


class SelfReviewService:
    """Capture a Dev self-review pass before opening a PR."""

    def __init__(self, repo: SQLiteSelfReviewRepository) -> None:
        self._repo = repo

    async def record(
        self,
        *,
        project_id: str,
        pr_url: str = "",
        task_id: str = "",
        codename: str = "",
        findings: tuple[SelfReviewFinding, ...] = (),
        summary: str = "",
    ) -> SelfReview:
        review = SelfReview(
            id=SelfReview.new_id(),
            project_id=project_id,
            pr_url=pr_url,
            task_id=task_id,
            codename=codename,
            findings=findings,
            summary=summary,
        )
        return await self._repo.add(review)

    async def list(self, project_id: str) -> list[SelfReview]:
        return await self._repo.list_for_project(project_id)

    def count_high(self, review: SelfReview) -> int:
        return review.high_count

    def make_finding(
        self,
        *,
        severity: FindingSeverity = FindingSeverity.LOW,
        category: str = "",
        message: str = "",
        waived: bool = False,
        waive_reason: str = "",
    ) -> SelfReviewFinding:
        return SelfReviewFinding(
            severity=severity,
            category=category,
            message=message,
            waived=waived,
            waive_reason=waive_reason,
        )


class CoverageDeltaService:
    """Record changed-lines coverage deltas per PR."""

    def __init__(
        self,
        repo: SQLiteCoverageDeltaRepository,
        *,
        default_threshold_pct: float = 80.0,
    ) -> None:
        self._repo = repo
        self._threshold = default_threshold_pct

    async def record(
        self,
        *,
        project_id: str,
        pr_url: str = "",
        task_id: str = "",
        codename: str = "",
        total_before_pct: float = 0.0,
        total_after_pct: float = 0.0,
        changed_lines_pct: float = 0.0,
        changed_lines: int = 0,
        missed_lines: int = 0,
        threshold_pct: float | None = None,
    ) -> CoverageDelta:
        delta = CoverageDelta(
            id=CoverageDelta.new_id(),
            project_id=project_id,
            pr_url=pr_url,
            task_id=task_id,
            codename=codename,
            total_before_pct=total_before_pct,
            total_after_pct=total_after_pct,
            changed_lines_pct=changed_lines_pct,
            changed_lines=changed_lines,
            missed_lines=missed_lines,
            threshold_pct=self._threshold if threshold_pct is None else threshold_pct,
        )
        return await self._repo.add(delta)

    async def list(self, project_id: str) -> list[CoverageDelta]:
        return await self._repo.list_for_project(project_id)

    async def latest_for_pr(self, pr_url: str) -> CoverageDelta | None:
        return await self._repo.latest_for_pr(pr_url)
