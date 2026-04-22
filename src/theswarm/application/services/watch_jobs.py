"""Scheduled watch jobs for the PO.

The jobs here intentionally accept pluggable *source* callables so tests can
pass deterministic fakes. Live wiring will hand real adapters (GitHub API,
RSS feed reader, HN API, etc.) — those come in a later sprint once the
dashboard surfaces are landed.

A watch job produces a list of ``Signal`` dicts. The runner persists them via
``ProposalService`` (which also records them against the Signal repo) so they
show up both on the Signals panel and as new Proposals in the inbox.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable, Protocol

from theswarm.application.services.proposal_service import ProposalService
from theswarm.domain.product.entities import Signal
from theswarm.domain.product.value_objects import SignalKind, SignalSeverity

log = logging.getLogger(__name__)

SignalSource = Callable[[str], Awaitable[list[dict]]]
"""A source fetches raw observations for a project_id; returns dicts.

Each dict may include: title, body, source_url, source_name, severity, tags,
metadata. The runner fills in id, project_id, kind, observed_at.
"""


@dataclass(frozen=True)
class WatchReport:
    project_id: str
    kind: SignalKind
    signals_created: int = 0
    proposals_created: int = 0
    errors: tuple[str, ...] = ()


class ProjectRepoPort(Protocol):
    async def list_active(self) -> list: ...


class WatchRunner:
    """Runs the competitor / ecosystem scans for each active project."""

    def __init__(
        self,
        project_repo: ProjectRepoPort,
        proposal_service: ProposalService,
        *,
        competitor_source: SignalSource | None = None,
        ecosystem_source: SignalSource | None = None,
        min_confidence: float = 0.55,
    ) -> None:
        self._projects = project_repo
        self._proposals = proposal_service
        self._competitor_source = competitor_source
        self._ecosystem_source = ecosystem_source
        self._min_confidence = min_confidence

    async def run_competitor_watch(self) -> list[WatchReport]:
        if self._competitor_source is None:
            return []
        return await self._run_all(SignalKind.COMPETITOR, self._competitor_source)

    async def run_ecosystem_watch(self) -> list[WatchReport]:
        if self._ecosystem_source is None:
            return []
        return await self._run_all(SignalKind.ECOSYSTEM, self._ecosystem_source)

    async def _run_all(
        self, kind: SignalKind, source: SignalSource,
    ) -> list[WatchReport]:
        projects = await self._projects.list_active()
        reports: list[WatchReport] = []
        for project in projects:
            pid = getattr(project, "id", None) or getattr(project, "project_id", "")
            if not pid:
                continue
            reports.append(await self._scan_project(pid, kind, source))
        return reports

    async def _scan_project(
        self, project_id: str, kind: SignalKind, source: SignalSource,
    ) -> WatchReport:
        signals_created = 0
        proposals_created = 0
        errors: list[str] = []
        try:
            raw_items = await source(project_id)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("watch source failed for %s", project_id)
            return WatchReport(
                project_id=project_id, kind=kind, errors=(str(exc),),
            )
        for raw in raw_items:
            try:
                severity_str = raw.get("severity", SignalSeverity.INFO.value)
                try:
                    severity = SignalSeverity(severity_str)
                except ValueError:
                    severity = SignalSeverity.INFO
                signal = Signal(
                    id=Signal.new_id(),
                    project_id=project_id,
                    kind=kind,
                    severity=severity,
                    title=str(raw.get("title", "")).strip(),
                    body=str(raw.get("body", "")),
                    source_url=str(raw.get("source_url", "")),
                    source_name=str(raw.get("source_name", "")),
                    tags=tuple(raw.get("tags", ())),
                    observed_at=datetime.now(timezone.utc),
                    metadata=dict(raw.get("metadata", {})),
                )
                confidence = float(raw.get("confidence", 0.6))
                if confidence < self._min_confidence and severity not in (
                    SignalSeverity.THREAT, SignalSeverity.OPPORTUNITY,
                ):
                    # Store the signal but skip proposal creation.
                    continue
                await self._proposals.propose_from_signal(
                    project_id=project_id,
                    signal=signal,
                    confidence=confidence,
                )
                signals_created += 1
                proposals_created += 1
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("failed to ingest signal for %s", project_id)
                errors.append(str(exc))
        return WatchReport(
            project_id=project_id,
            kind=kind,
            signals_created=signals_created,
            proposals_created=proposals_created,
            errors=tuple(errors),
        )
