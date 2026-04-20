"""Sprint E M4 — Improver agent: StoryRejected → CLAUDE.md PR."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest

from theswarm.application.events.bus import EventBus
from theswarm.application.services.improver_agent import ImproverAgent
from theswarm.domain.memory.value_objects import MemoryCategory
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.domain.reporting.events import StoryRejected
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteMemoryStore,
    SQLiteProjectRepository,
    init_db,
)


FIXED_NOW = datetime(2026, 4, 20, 12, 30, 15, tzinfo=timezone.utc)


@dataclass
class _FakeReport:
    id: str
    project_id: str


class _FakeReportRepo:
    def __init__(self) -> None:
        self._reports: dict[str, _FakeReport] = {}

    def add(self, report_id: str, project_id: str) -> None:
        self._reports[report_id] = _FakeReport(report_id, project_id)

    async def get(self, report_id: str) -> _FakeReport | None:
        return self._reports.get(report_id)


class _FakeVcs:
    def __init__(self, initial_content: str = "", missing: bool = False) -> None:
        self.files: dict[str, str] = {} if missing else {"CLAUDE.md": initial_content}
        self.branches: list[tuple[str, str]] = []
        self.updates: list[dict] = []
        self.prs: list[dict] = []
        self.raise_on_get: bool = missing

    async def get_file_content(self, path: str, ref: str = "main") -> str:
        if self.raise_on_get and path not in self.files:
            raise RuntimeError("file not found")
        return self.files.get(path, "")

    async def create_branch(self, branch_name: str, from_branch: str = "main") -> None:
        self.branches.append((branch_name, from_branch))

    async def update_file(
        self, path: str, content: str, branch: str, commit_message: str,
    ) -> None:
        self.files[path] = content
        self.updates.append({
            "path": path, "content": content,
            "branch": branch, "message": commit_message,
        })

    async def create_pr(
        self, branch: str, base: str, title: str, body: str = "",
    ) -> dict:
        pr = {
            "number": len(self.prs) + 1,
            "branch": branch, "base": base,
            "title": title, "body": body,
            "url": f"https://fake/pr/{len(self.prs) + 1}",
        }
        self.prs.append(pr)
        return pr


@pytest.fixture
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "improver.db"))
    yield conn
    await conn.close()


def _fixed_clock() -> datetime:
    return FIXED_NOW


async def _mk_agent(
    db,
    vcs: _FakeVcs,
    *,
    with_memory: bool = True,
) -> tuple[ImproverAgent, _FakeReportRepo, SQLiteProjectRepository]:
    project_repo = SQLiteProjectRepository(db)
    await project_repo.save(Project(id="alpha", repo=RepoUrl("org/alpha-repo")))
    report_repo = _FakeReportRepo()
    report_repo.add("rpt-1", "alpha")
    memory_store = SQLiteMemoryStore(db) if with_memory else None
    agent = ImproverAgent(
        vcs_factory=lambda repo: vcs,
        project_repo=project_repo,
        report_repo=report_repo,
        memory_store=memory_store,
        clock=_fixed_clock,
    )
    return agent, report_repo, project_repo


async def test_improver_opens_pr_with_new_lessons_section(db):
    vcs = _FakeVcs(initial_content="# CLAUDE.md\n\nExisting guidance.\n")
    agent, _, _ = await _mk_agent(db, vcs)

    outcome = await agent.on_story_rejected(StoryRejected(
        report_id="rpt-1", ticket_id="TKT-42",
        user="alice", comment="broke the landing page",
    ))

    assert outcome is not None
    assert len(vcs.branches) == 1
    assert len(vcs.updates) == 1
    assert len(vcs.prs) == 1
    pr = vcs.prs[0]
    assert "TKT-42" in pr["title"]
    new_content = vcs.files["CLAUDE.md"]
    assert "## Lessons from rejected work" in new_content
    assert "TKT-42" in new_content
    assert "broke the landing page" in new_content
    assert "Existing guidance." in new_content


async def test_improver_appends_to_existing_section(db):
    seed = (
        "# CLAUDE.md\n\n"
        "## Lessons from rejected work\n\n"
        "- 2026-01-01 · story `OLD-1` rejected by bob: flakey tests\n"
    )
    vcs = _FakeVcs(initial_content=seed)
    agent, _, _ = await _mk_agent(db, vcs)

    await agent.on_story_rejected(StoryRejected(
        report_id="rpt-1", ticket_id="TKT-99",
        user="carol", comment="missing accessibility",
    ))

    new_content = vcs.files["CLAUDE.md"]
    # Existing bullet preserved, new bullet added after.
    assert "OLD-1" in new_content
    assert "TKT-99" in new_content
    old_idx = new_content.index("OLD-1")
    new_idx = new_content.index("TKT-99")
    assert old_idx < new_idx
    # Only one Lessons heading.
    assert new_content.count("## Lessons from rejected work") == 1


async def test_improver_skips_when_lesson_already_present(db):
    lesson_line = (
        f"- {FIXED_NOW.strftime('%Y-%m-%d')} · story `TKT-7` rejected by alice: "
        "no design review"
    )
    seed = f"# CLAUDE.md\n\n## Lessons from rejected work\n\n{lesson_line}\n"
    vcs = _FakeVcs(initial_content=seed)
    agent, _, _ = await _mk_agent(db, vcs)

    outcome = await agent.on_story_rejected(StoryRejected(
        report_id="rpt-1", ticket_id="TKT-7",
        user="alice", comment="no design review",
    ))
    assert outcome is None
    assert vcs.prs == []
    assert vcs.updates == []


async def test_improver_creates_file_when_missing(db):
    vcs = _FakeVcs(missing=True)
    agent, _, _ = await _mk_agent(db, vcs)

    outcome = await agent.on_story_rejected(StoryRejected(
        report_id="rpt-1", ticket_id="TKT-2",
        user="bob", comment="",
    ))
    assert outcome is not None
    assert "CLAUDE.md" in vcs.files
    assert "## Lessons from rejected work" in vcs.files["CLAUDE.md"]
    assert "TKT-2" in vcs.files["CLAUDE.md"]


async def test_improver_persists_memory_entry(db):
    vcs = _FakeVcs(initial_content="# CLAUDE.md\n")
    agent, _, _ = await _mk_agent(db, vcs)
    await agent.on_story_rejected(StoryRejected(
        report_id="rpt-1", ticket_id="TKT-11",
        user="dee", comment="bad UX copy",
    ))
    store = SQLiteMemoryStore(db)
    entries = await store.query(project_id="alpha", agent="improver")
    assert len(entries) == 1
    assert entries[0].category == MemoryCategory.IMPROVEMENTS
    assert "TKT-11" in entries[0].content


async def test_improver_skips_when_project_missing(db):
    vcs = _FakeVcs(initial_content="")
    agent, report_repo, _ = await _mk_agent(db, vcs)
    report_repo.add("rpt-2", "ghost-project")
    outcome = await agent.on_story_rejected(StoryRejected(
        report_id="rpt-2", ticket_id="TKT-3",
        user="x", comment="y",
    ))
    assert outcome is None
    assert vcs.prs == []


async def test_improver_skips_when_no_vcs_factory(db):
    project_repo = SQLiteProjectRepository(db)
    await project_repo.save(Project(id="alpha", repo=RepoUrl("org/alpha-repo")))
    report_repo = _FakeReportRepo()
    report_repo.add("rpt-1", "alpha")
    agent = ImproverAgent(
        vcs_factory=None, project_repo=project_repo,
        report_repo=report_repo, memory_store=None, clock=_fixed_clock,
    )
    outcome = await agent.on_story_rejected(StoryRejected(
        report_id="rpt-1", ticket_id="TKT-0",
        user="x", comment="y",
    ))
    assert outcome is None


async def test_improver_wired_to_event_bus(db):
    from theswarm.infrastructure.persistence.sqlite_repos import SQLiteCycleRepository
    from theswarm.presentation.web.app import create_web_app
    from theswarm.presentation.web.sse import SSEHub

    project_repo = SQLiteProjectRepository(db)
    await project_repo.save(Project(id="alpha", repo=RepoUrl("org/alpha-repo")))
    bus = EventBus()

    vcs = _FakeVcs(initial_content="# CLAUDE.md\n")
    report_repo = _FakeReportRepo()
    report_repo.add("rpt-1", "alpha")

    app = create_web_app(
        project_repo, SQLiteCycleRepository(db), bus, SSEHub(),
        memory_store=SQLiteMemoryStore(db),
        report_repo=report_repo,
        vcs_factory=lambda repo: vcs,
    )
    assert getattr(app.state, "improver_agent", None) is not None

    await bus.publish(StoryRejected(
        report_id="rpt-1", ticket_id="TKT-BUS",
        user="reviewer", comment="docs were unclear",
    ))
    # Give the bus time to dispatch sync handler
    assert len(vcs.prs) == 1
    assert "TKT-BUS" in vcs.prs[0]["title"]
