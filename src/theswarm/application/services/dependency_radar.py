"""Dependency radar — periodic scan for CVEs and stale packages.

The runner accepts a pluggable ``DepScanner`` callable so tests can inject a
fake. Live wiring will supply adapters for pip-audit, osv-scanner or GitHub's
advisory API. Findings are persisted through ``SQLiteDepFindingRepository``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Protocol

from theswarm.domain.techlead.entities import DepFinding
from theswarm.domain.techlead.value_objects import DepSeverity
from theswarm.infrastructure.techlead.dep_repo import SQLiteDepFindingRepository

log = logging.getLogger(__name__)

DepScanner = Callable[[str], Awaitable[list[dict]]]
"""Fetch raw findings for a project. Each dict may include:
    package, installed_version, advisory_id, severity, summary, fixed_version,
    source, url.
"""


@dataclass(frozen=True)
class DepScanReport:
    project_id: str
    scanner: str
    findings_new: int = 0
    findings_refreshed: int = 0
    errors: tuple[str, ...] = ()


class ProjectRepoPort(Protocol):
    async def list_all(self) -> list: ...


class DependencyRadar:
    """Runs configured scanners across all projects and persists findings."""

    def __init__(
        self,
        project_repo: ProjectRepoPort,
        dep_repo: SQLiteDepFindingRepository,
        *,
        scanners: dict[str, DepScanner] | None = None,
    ) -> None:
        self._projects = project_repo
        self._deps = dep_repo
        self._scanners: dict[str, DepScanner] = dict(scanners or {})

    def register_scanner(self, name: str, scanner: DepScanner) -> None:
        self._scanners[name] = scanner

    async def run_all(self) -> list[DepScanReport]:
        projects = await self._projects.list_all()
        reports: list[DepScanReport] = []
        for project in projects:
            pid = getattr(project, "id", None) or getattr(project, "project_id", "")
            if not pid:
                continue
            for name, scanner in self._scanners.items():
                reports.append(await self.scan_project(pid, name, scanner))
        return reports

    async def scan_project(
        self, project_id: str, scanner_name: str, scanner: DepScanner,
    ) -> DepScanReport:
        new = 0
        refreshed = 0
        errors: list[str] = []
        try:
            raw_items = await scanner(project_id)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("dep scan failed for %s/%s", project_id, scanner_name)
            return DepScanReport(
                project_id=project_id, scanner=scanner_name, errors=(str(exc),),
            )
        for raw in raw_items:
            try:
                severity_str = raw.get("severity", DepSeverity.INFO.value)
                try:
                    severity = DepSeverity(severity_str)
                except ValueError:
                    severity = DepSeverity.INFO
                package = str(raw.get("package", "")).strip()
                advisory_id = str(raw.get("advisory_id", "")).strip()
                if not package:
                    continue
                # See whether we already have this pin to count new vs refresh.
                existing = await self._deps.list_for_project(
                    project_id, include_dismissed=True,
                )
                already = any(
                    f.package == package and f.advisory_id == advisory_id
                    for f in existing
                )
                finding = DepFinding(
                    id=DepFinding.new_id(),
                    project_id=project_id,
                    package=package,
                    installed_version=str(raw.get("installed_version", "")),
                    advisory_id=advisory_id,
                    severity=severity,
                    summary=str(raw.get("summary", "")),
                    fixed_version=str(raw.get("fixed_version", "")),
                    source=str(raw.get("source", scanner_name)),
                    url=str(raw.get("url", "")),
                )
                await self._deps.upsert(finding)
                if already:
                    refreshed += 1
                else:
                    new += 1
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("failed to ingest dep finding")
                errors.append(str(exc))
        return DepScanReport(
            project_id=project_id,
            scanner=scanner_name,
            findings_new=new,
            findings_refreshed=refreshed,
            errors=tuple(errors),
        )
