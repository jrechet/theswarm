"""Routes for the sprint composer — draft + create endpoints."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.application.events.bus import EventBus
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.value_objects import RepoUrl
from theswarm.infrastructure.persistence.sqlite_repos import (
    SQLiteCycleRepository,
    SQLiteProjectRepository,
    init_db,
)
from theswarm.presentation.web.app import create_web_app
from theswarm.presentation.web.sse import SSEHub


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "sprint.db"))
    yield conn
    await conn.close()


@pytest.fixture()
def app(db):
    return create_web_app(
        SQLiteProjectRepository(db), SQLiteCycleRepository(db),
        EventBus(), SSEHub(), db=db,
    )


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _seed_project(db, pid="p1", repo="o/p1"):
    project_repo = SQLiteProjectRepository(db)
    await project_repo.save(Project(id=pid, repo=RepoUrl(repo)))


_FAKE_RESPONSE = (
    '{"issues": ['
    '{"title": "Add LICENSE", "body": "MIT.", "labels": ["status:backlog","role:dev"]},'
    '{"title": "Verify LICENSE", "body": "Check headers.", "labels": ["component:tests"]}'
    ']}'
)


class TestDraftEndpoint:
    async def test_draft_returns_parsed_issues(self, client, db):
        await _seed_project(db)
        with patch("theswarm.application.services.sprint_composer.SprintComposer.draft",
                   new_callable=AsyncMock) as mock_draft:
            from theswarm.application.services.sprint_composer import (
                IssueDraft,
                SprintDraft,
            )
            mock_draft.return_value = SprintDraft(
                request="x",
                issues=(
                    IssueDraft(
                        title="Add LICENSE", body="MIT.",
                        labels=("status:backlog", "role:dev"),
                    ),
                ),
            )
            r = await client.post(
                "/projects/p1/sprints/draft", data={"description": "Add a license"},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["issues"][0]["title"] == "Add LICENSE"
        assert "status:backlog" in body["issues"][0]["labels"]

    async def test_draft_404_for_unknown_project(self, client):
        r = await client.post(
            "/projects/ghost/sprints/draft", data={"description": "x"},
        )
        assert r.status_code == 404

    async def test_draft_400_for_overlong_request(self, client, db):
        await _seed_project(db)
        with patch("theswarm.application.services.sprint_composer.SprintComposer.draft",
                   new_callable=AsyncMock) as mock_draft:
            mock_draft.side_effect = ValueError("too long")
            r = await client.post(
                "/projects/p1/sprints/draft", data={"description": "x" * 5000},
            )
        assert r.status_code == 400


class TestCreateEndpoint:
    async def test_create_pushes_to_github(self, client, db):
        await _seed_project(db)
        with patch("theswarm.tools.github.GitHubClient") as mock_cls:
            instance = mock_cls.return_value
            instance.create_issue = AsyncMock(return_value={
                "number": 42, "title": "Add LICENSE", "html_url": "https://gh/x/42",
            })
            r = await client.post(
                "/projects/p1/sprints/create",
                json={"issues": [
                    {"title": "Add LICENSE", "body": "MIT.", "labels": ["status:backlog"]},
                ]},
            )
        assert r.status_code == 200
        body = r.json()
        assert len(body["created"]) == 1
        assert body["created"][0]["number"] == 42

    async def test_create_400_when_no_issues(self, client, db):
        await _seed_project(db)
        r = await client.post(
            "/projects/p1/sprints/create", json={"issues": []},
        )
        assert r.status_code == 400

    async def test_create_collects_errors_per_issue(self, client, db):
        await _seed_project(db)
        with patch("theswarm.tools.github.GitHubClient") as mock_cls:
            instance = mock_cls.return_value
            instance.create_issue = AsyncMock(side_effect=RuntimeError("API down"))
            r = await client.post(
                "/projects/p1/sprints/create",
                json={"issues": [{"title": "Bad"}]},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["created"] == []
        assert any("API down" in e for e in body["errors"])
