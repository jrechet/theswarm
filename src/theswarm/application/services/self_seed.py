"""Self-seed — register TheSwarm as a project and create one demo per sprint.

Used to bootstrap the production dashboard with dogfooding data: each sprint
from ``theswarm-04.md`` becomes a DemoReport with stories matching the features
shipped in that sprint. Optional sprint videos under ``docs/demos/sprint-*.webm``
are picked up automatically and attached as artifacts.

Idempotent: re-running replaces existing rows with matching IDs.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

from theswarm.domain.cycles.entities import Cycle, PhaseExecution
from theswarm.domain.cycles.value_objects import (
    Budget,
    CycleId,
    CycleStatus,
    PhaseStatus,
)
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.domain.reporting.entities import DemoReport, ReportSummary, StoryReport
from theswarm.domain.reporting.value_objects import (
    Artifact,
    ArtifactType,
    QualityGate,
    QualityStatus,
)


_PROJECT_ID = "theswarm"
_REPO = "jrechet/theswarm"
_DEFAULT_CREATED_AT = datetime(2026, 4, 20, 12, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Story:
    ticket_id: str
    title: str


@dataclass(frozen=True)
class _Sprint:
    letter: str
    title: str
    subtitle: str
    stories: tuple[_Story, ...]
    tests_total: int
    learnings: tuple[str, ...]
    video_filename: str = ""


_SPRINTS: tuple[_Sprint, ...] = (
    _Sprint(
        letter="A",
        title="Sprint A — Fondations démo push",
        subtitle="SSE toast, Mattermost DM, before/after, per-story video, thumbnails",
        stories=(
            _Story("F1", "DemoReady event + SSE toast + Mattermost DM"),
            _Story("F2", "Before/After screenshot per story"),
            _Story("F3", "Per-story E2E walkthrough video"),
            _Story("F4", "Thumbnail + GIF generation (ffmpeg)"),
        ),
        tests_total=1150,
        learnings=(
            "Per-story artifact mapping deferred until ticket↔PR resolution lands",
            "ffmpeg is the pragmatic thumbnail path — no extra Python deps",
        ),
        video_filename="sprint-A.webm",
    ),
    _Sprint(
        letter="B",
        title="Sprint B — Controls in-dashboard",
        subtitle="ProjectConfig editor, effort slider, secret vault, cost caps, kill switch",
        stories=(
            _Story("C1", "ProjectConfig editor (models / effort / caps)"),
            _Story("C2", "Effort slider low/medium/high"),
            _Story("C3", "Per-project Fernet secret vault"),
            _Story("C4", "Daily / monthly cost caps"),
            _Story("C6", "Kill-switch (pause / resume)"),
        ),
        tests_total=1180,
        learnings=(
            "Fernet keys must be lazy-initialised so restarts don't block",
            "CycleBlocked → SSE toast pattern generalises beyond budget guard",
        ),
        video_filename="sprint-B.webm",
    ),
    _Sprint(
        letter="C",
        title="Sprint C — Approve/Reject inline + preview iframe",
        subtitle="Shareable public demo URL, inline review, live cycle preview",
        stories=(
            _Story("F5", "Shareable public demo URL /d/<short>"),
            _Story("F6", "Approve / Reject / Comment inline in player"),
            _Story("F9", "Live preview iframe during cycle"),
        ),
        tests_total=1210,
        learnings=(
            "sha256 prefix gives stable, guessable-resistant public slugs",
            "Idempotency via a story_actions table is cleaner than in-memory guards",
        ),
        video_filename="sprint-C.webm",
    ),
    _Sprint(
        letter="D",
        title="Sprint D — Observabilité live & replay",
        subtitle="Activity feed, cycle replay scrubber, agent thoughts, Web Push, cost preview",
        stories=(
            _Story("V1", "Per-agent live activity feed"),
            _Story("V2", "Cycle replay with scrubber"),
            _Story("V3", "Agent thought / step panel"),
            _Story("V5", "Web Push notifications"),
            _Story("C5", "Cost preview modal before run"),
        ),
        tests_total=1255,
        learnings=(
            "Event sourcing for replay is cheap when stored as JSONL blobs",
            "Web Push needs an opt-in bell — silent subscription ruins trust",
        ),
        video_filename="sprint-D.webm",
    ),
    _Sprint(
        letter="E",
        title="Sprint E — Mémoire vivante & improver",
        subtitle="Memory viewer, retrospective phase, Improver agent PRs",
        stories=(
            _Story("M1", "Memory viewer /projects/{id}/memory"),
            _Story("M2", "End-of-cycle retrospective phase"),
            _Story("M4", "Improver agent → CLAUDE.md PR on rejection"),
        ),
        tests_total=1280,
        learnings=(
            "Rule-based retrospectives ship faster than LLM summarisation",
            "Idempotent CLAUDE.md PR logic prevents a rejection storm on one story",
        ),
        video_filename="sprint-E.webm",
    ),
    _Sprint(
        letter="F",
        title="Sprint F — Pluggabilité & polish",
        subtitle="/swarm implement webhook, Linear adapter, memory compaction, speed, A/B comparator",
        stories=(
            _Story("P1", "GitHub /swarm implement issue_comment webhook"),
            _Story("P2", "Linear ticket source adapter"),
            _Story("M3", "Memory compaction cron (nightly dedup + trim)"),
            _Story("F7", "Player speed control (0.5× / 1× / 2×)"),
            _Story("F8", "A/B demo comparator /demos/compare?a=&b="),
        ),
        tests_total=1315,
        learnings=(
            "Protocol-based Linear client keeps the adapter swap-friendly",
            "Marker entries on compaction make the size drop auditable later",
        ),
        video_filename="sprint-F.webm",
    ),
    _Sprint(
        letter="G",
        title="Sprint G — Résilience & fail-safes",
        subtitle="Phase checkpoints, adaptive Claude retry, GitHub circuit breaker, QA readiness, resume UI",
        stories=(
            _Story("G1", "Cycle phase checkpoint persistence + /api/cycles/{id}/checkpoints"),
            _Story("G2", "Adaptive Claude timeout with exponential backoff + jitter"),
            _Story("G3", "GitHub client rate-limit circuit breaker"),
            _Story("G4", "QA HTTP readiness watchdog replacing blind sleeps"),
            _Story("G5", "Cycle Resume UI + POST /cycles/{id}/resume"),
        ),
        tests_total=1342,
        learnings=(
            "Injectable sleep_fn/rng makes backoff tests deterministic without monkeypatching time",
            "Immediate-trip errors (RateLimitExceeded) belong at the breaker layer, not in each caller",
        ),
        video_filename="sprint-G.webm",
    ),
)


class _ProjectRepoLike(Protocol):
    async def save(self, project: Project) -> None: ...
    async def get(self, project_id: str) -> Project | None: ...


class _ReportRepoLike(Protocol):
    async def save(self, report: DemoReport) -> None: ...
    async def get(self, report_id: str) -> DemoReport | None: ...


class _CycleRepoLike(Protocol):
    async def save(self, cycle: Cycle) -> None: ...
    async def get(self, cycle_id: CycleId) -> Cycle | None: ...


@dataclass(frozen=True)
class SelfSeedResult:
    project_created: bool
    project_updated: bool
    reports_saved: tuple[str, ...]
    videos_attached: tuple[str, ...]
    cycles_saved: tuple[str, ...] = ()


def _sprint_report_id(letter: str) -> str:
    return f"theswarm-sprint-{letter.lower()}"


def _sprint_cycle_id(letter: str) -> CycleId:
    return CycleId(f"theswarm-sprint-{letter.lower()}-cycle")


def _sprint_created_at(index: int) -> datetime:
    # Space sprints 10 minutes apart starting 2026-04-20 12:00 UTC so they
    # sort chronologically on the dashboard. timedelta handles >5 sprints cleanly.
    return _DEFAULT_CREATED_AT + timedelta(minutes=index * 10)


def _build_quality_gates() -> tuple[QualityGate, ...]:
    return (
        QualityGate(name="Unit tests", status=QualityStatus.PASS, detail="All green"),
        QualityGate(name="Type checks", status=QualityStatus.PASS),
        QualityGate(name="Lint", status=QualityStatus.PASS),
        QualityGate(name="Security scan", status=QualityStatus.PASS, detail="semgrep clean"),
    )


def _summary_for(sprint: _Sprint) -> ReportSummary:
    n = len(sprint.stories)
    return ReportSummary(
        stories_completed=n,
        stories_total=n,
        prs_merged=n,
        tests_passing=sprint.tests_total,
        tests_total=sprint.tests_total,
        coverage_percent=85.0,
        cost_usd=0.37,
    )


def _attach_sprint_video(
    sprint: _Sprint,
    report_id: str,
    cycle_id: CycleId,
    video_source_dir: Path | None,
    artifacts_base_dir: Path | None,
) -> Artifact | None:
    """Copy ``sprint-*.webm`` from source to artifact store; return Artifact or None."""
    if not sprint.video_filename or video_source_dir is None or artifacts_base_dir is None:
        return None
    source = video_source_dir / sprint.video_filename
    if not source.is_file():
        return None
    dest_dir = artifacts_base_dir / str(cycle_id) / "video"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / sprint.video_filename
    if not dest.exists() or dest.stat().st_size != source.stat().st_size:
        shutil.copy2(source, dest)
    rel_path = f"{cycle_id}/video/{sprint.video_filename}"
    return Artifact(
        type=ArtifactType.VIDEO,
        label=f"Sprint {sprint.letter} walkthrough",
        path=rel_path,
        mime_type="video/webm",
        size_bytes=dest.stat().st_size,
    )


def _build_stories(sprint: _Sprint) -> tuple[StoryReport, ...]:
    return tuple(
        StoryReport(
            ticket_id=f"{sprint.letter}-{story.ticket_id}",
            title=story.title,
            status="completed",
            pr_number=None,
        )
        for story in sprint.stories
    )


def _build_cycle(sprint: _Sprint, created_at: datetime) -> Cycle:
    """Build a completed Cycle entity matching a seeded sprint demo.

    Gives the dashboard real cycle rows so /cycles/, "Recent Cycles",
    "Success Rate" and "Cost 7d" stats reflect the sprint history.
    """
    n = len(sprint.stories)
    # Tokens per phase roughly matching $0.37 total cost at Haiku-class rates.
    # Distribution: dev dominates, QA second, PO/TL lighter. Sums to ~150K tokens.
    phase_defs = (
        ("po_morning", "po", f"Selected {n} backlog stories", 12_000),
        ("techlead_breakdown", "techlead", "Split stories into dev-ready sub-tasks", 18_000),
        ("dev_loop", "dev", f"Implemented {n} stories, opened {n} PRs", 82_000),
        ("qa", "qa", "Ran unit + E2E + security gates", 28_000),
        ("po_evening", "po", "Published demo report", 10_000),
    )
    # Each phase spans 1 minute starting at created_at.
    phases = tuple(
        PhaseExecution(
            phase=name,
            agent=agent,
            started_at=created_at + timedelta(minutes=idx),
            completed_at=created_at + timedelta(minutes=idx + 1),
            status=PhaseStatus.COMPLETED,
            summary=summary,
            tokens_used=tokens,
        )
        for idx, (name, agent, summary, tokens) in enumerate(phase_defs)
    )
    completed_at = created_at + timedelta(minutes=len(phase_defs))
    prs = tuple(100 + idx for idx in range(n))
    return Cycle(
        id=_sprint_cycle_id(sprint.letter),
        project_id=_PROJECT_ID,
        status=CycleStatus.COMPLETED,
        triggered_by="self-seed",
        started_at=created_at,
        completed_at=completed_at,
        phases=phases,
        budgets=(Budget(role="claude", limit=200_000, used=9_400),),
        total_cost_usd=0.37,
        prs_opened=prs,
        prs_merged=prs,
    )


async def seed_self(
    project_repo: _ProjectRepoLike,
    report_repo: _ReportRepoLike,
    *,
    cycle_repo: _CycleRepoLike | None = None,
    video_source_dir: Path | None = None,
    artifacts_base_dir: Path | None = None,
) -> SelfSeedResult:
    """Register the TheSwarm project and one demo report per sprint.

    - ``cycle_repo``: if provided, also insert a completed Cycle row per sprint so
      the /cycles/ page and home-page stats are populated consistently with the
      demo list.
    - ``video_source_dir``: directory holding ``sprint-*.webm`` to attach (optional).
    - ``artifacts_base_dir``: base artifact store dir; required if attaching videos.
    """
    existing = await project_repo.get(_PROJECT_ID)
    project = Project(
        id=_PROJECT_ID,
        repo=RepoUrl(_REPO),
        team_channel="theswarm",
    )
    await project_repo.save(project)
    project_created = existing is None
    project_updated = existing is not None and existing != project

    saved_ids: list[str] = []
    attached_videos: list[str] = []
    cycles_saved: list[str] = []

    for idx, sprint in enumerate(_SPRINTS):
        report_id = _sprint_report_id(sprint.letter)
        cycle_id = _sprint_cycle_id(sprint.letter)
        created_at = _sprint_created_at(idx)

        artifacts: tuple[Artifact, ...] = ()
        video = _attach_sprint_video(
            sprint,
            report_id,
            cycle_id,
            video_source_dir,
            artifacts_base_dir,
        )
        if video is not None:
            artifacts = (video,)
            attached_videos.append(video.path)

        report = DemoReport(
            id=report_id,
            cycle_id=cycle_id,
            project_id=_PROJECT_ID,
            created_at=created_at,
            summary=_summary_for(sprint),
            stories=_build_stories(sprint),
            quality_gates=_build_quality_gates(),
            agent_learnings=sprint.learnings,
            artifacts=artifacts,
        )
        await report_repo.save(report)
        saved_ids.append(report_id)

        if cycle_repo is not None:
            cycle = _build_cycle(sprint, created_at)
            await cycle_repo.save(cycle)
            cycles_saved.append(str(cycle.id))

    return SelfSeedResult(
        project_created=project_created,
        project_updated=project_updated,
        reports_saved=tuple(saved_ids),
        videos_attached=tuple(attached_videos),
        cycles_saved=tuple(cycles_saved),
    )
