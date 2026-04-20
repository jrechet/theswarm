"""Sprint E M4 — Improver agent.

When a reviewer rejects a story, the Improver agent proposes a diff on the
target repo's ``CLAUDE.md`` and opens a PR. The goal is to turn human
rejections into durable guidance that the next cycle will pick up.

The rule is deliberately mechanical: append a dated entry to a
``## Lessons from rejected work`` section at the bottom of the file,
preserving whatever is already there.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from theswarm.domain.memory.entities import MemoryEntry
from theswarm.domain.memory.ports import MemoryStore
from theswarm.domain.memory.value_objects import MemoryCategory, ProjectScope
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.ports import ProjectRepository
from theswarm.domain.reporting.events import StoryRejected

log = logging.getLogger(__name__)

_LESSONS_HEADING = "## Lessons from rejected work"
_DEFAULT_BRANCH_PREFIX = "improver/claude-md-"
_TARGET_FILE = "CLAUDE.md"


class _VcsLike(Protocol):
    async def get_file_content(self, path: str, ref: str = "main") -> str: ...
    async def create_branch(self, branch_name: str, from_branch: str = "main") -> None: ...
    async def update_file(
        self, path: str, content: str, branch: str, commit_message: str,
    ) -> None: ...
    async def create_pr(
        self, branch: str, base: str, title: str, body: str = "",
    ) -> dict: ...


class ReportLookup(Protocol):
    async def get(self, report_id: str): ...


@dataclass(frozen=True)
class ImproverOutcome:
    branch: str
    pr: dict
    lesson: str


class ImproverAgent:
    """React to StoryRejected by proposing a CLAUDE.md improvement PR."""

    def __init__(
        self,
        vcs_factory: Callable[[str], _VcsLike] | None,
        project_repo: ProjectRepository,
        report_repo: ReportLookup | None = None,
        memory_store: MemoryStore | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._vcs_factory = vcs_factory
        self._project_repo = project_repo
        self._report_repo = report_repo
        self._memory_store = memory_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def on_story_rejected(self, event: StoryRejected) -> ImproverOutcome | None:
        if self._vcs_factory is None:
            log.info("Improver: no VCS factory configured, skipping PR creation.")
            return None

        project = await self._resolve_project(event.report_id)
        if project is None:
            log.info("Improver: could not resolve project for report %s", event.report_id)
            return None

        lesson = self._build_lesson(event)
        outcome = await self._open_improvement_pr(project, lesson, event.ticket_id)

        if outcome is not None and self._memory_store is not None:
            await self._memory_store.append([
                MemoryEntry(
                    category=MemoryCategory.IMPROVEMENTS,
                    content=lesson,
                    agent="improver",
                    scope=ProjectScope(project_id=project.id),
                    cycle_date=self._clock().strftime("%Y-%m-%d"),
                    created_at=self._clock(),
                )
            ])
        return outcome

    async def _resolve_project(self, report_id: str) -> Project | None:
        if self._report_repo is None:
            return None
        report = await self._report_repo.get(report_id)
        if report is None:
            return None
        return await self._project_repo.get(report.project_id)

    def _build_lesson(self, event: StoryRejected) -> str:
        date = self._clock().strftime("%Y-%m-%d")
        comment = event.comment.strip() or "(no comment provided)"
        return (
            f"- {date} · story `{event.ticket_id}` rejected by {event.user or 'reviewer'}: "
            f"{comment}"
        )

    async def _open_improvement_pr(
        self,
        project: Project,
        lesson: str,
        ticket_id: str,
    ) -> ImproverOutcome | None:
        vcs = self._vcs_factory(str(project.repo))
        base = project.default_branch or "main"

        try:
            current = await vcs.get_file_content(_TARGET_FILE, ref=base)
        except Exception:
            log.info("Improver: %s not found in %s; seeding new file", _TARGET_FILE, project.repo)
            current = ""

        updated = self._append_lesson(current, lesson)
        if updated == current:
            log.info("Improver: lesson already present; skipping PR")
            return None

        branch = f"{_DEFAULT_BRANCH_PREFIX}{ticket_id}-{self._clock().strftime('%Y%m%d%H%M%S')}"
        try:
            await vcs.create_branch(branch, from_branch=base)
            await vcs.update_file(
                _TARGET_FILE, updated, branch=branch,
                commit_message=f"docs(claude): record lesson from rejected {ticket_id}",
            )
            pr = await vcs.create_pr(
                branch=branch, base=base,
                title=f"Improver: record lesson from rejected {ticket_id}",
                body=(
                    "Automated proposal from the Improver agent.\n\n"
                    f"A reviewer rejected {ticket_id}. The following lesson has been "
                    f"appended to `{_TARGET_FILE}` so the next cycle picks it up:\n\n"
                    f"{lesson}\n"
                ),
            )
        except Exception:
            log.exception("Improver: failed to open CLAUDE.md PR")
            return None

        return ImproverOutcome(branch=branch, pr=pr, lesson=lesson)

    @staticmethod
    def _append_lesson(current: str, lesson: str) -> str:
        """Append ``lesson`` to the Lessons section, creating it if missing."""
        if lesson.strip() and lesson.strip() in current:
            return current

        lines = current.splitlines()
        heading_pattern = re.compile(r"^##\s+Lessons from rejected work\s*$", re.IGNORECASE)
        heading_index = next(
            (i for i, line in enumerate(lines) if heading_pattern.match(line)),
            None,
        )
        if heading_index is None:
            prefix = current.rstrip()
            sep = "\n\n" if prefix else ""
            return f"{prefix}{sep}{_LESSONS_HEADING}\n\n{lesson}\n"

        # Find end of section (next "## " heading or EOF).
        end = len(lines)
        for j in range(heading_index + 1, len(lines)):
            if lines[j].startswith("## "):
                end = j
                break

        insertion = heading_index + 1
        # Skip one blank line after the heading if present.
        if insertion < end and lines[insertion].strip() == "":
            insertion += 1
        # Walk past existing bullets to keep chronological order.
        while insertion < end and lines[insertion].startswith("- "):
            insertion += 1

        new_lines = lines[:insertion] + [lesson] + lines[insertion:]
        trailing_newline = "\n" if current.endswith("\n") else ""
        return "\n".join(new_lines) + trailing_newline
