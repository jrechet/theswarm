"""SQLiteSprintRepository — composer-created sprints."""

from __future__ import annotations

import pytest

from theswarm.infrastructure.persistence.sprint_repo import (
    Sprint,
    SQLiteSprintRepository,
    _new_sprint_id,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db


@pytest.fixture()
async def repo(tmp_path):
    conn = await init_db(str(tmp_path / "sprints.db"))
    yield SQLiteSprintRepository(conn)
    await conn.close()


def test_id_format():
    sid = _new_sprint_id()
    assert sid.startswith("sprint-")
    assert len(sid) == len("sprint-YYYYMMDD-HHMM-XXXX")


async def test_create_persists_and_returns_sprint(repo):
    s = await repo.create(project_id="p1", request="add a license", issue_numbers=[42, 43])
    assert s.project_id == "p1"
    assert s.issue_numbers == (42, 43)
    fetched = await repo.get(s.id)
    assert fetched is not None
    assert fetched.request == "add a license"


async def test_list_orders_newest_first(repo):
    s1 = await repo.create(project_id="p1", request="first", issue_numbers=[1])
    s2 = await repo.create(project_id="p1", request="second", issue_numbers=[2])
    rows = await repo.list_for_project("p1")
    assert [r.id for r in rows] == [s2.id, s1.id]


async def test_list_filters_by_project(repo):
    await repo.create(project_id="p1", request="x", issue_numbers=[1])
    await repo.create(project_id="p2", request="y", issue_numbers=[2])
    rows = await repo.list_for_project("p1")
    assert len(rows) == 1
    assert rows[0].request == "x"


async def test_get_returns_none_for_unknown(repo):
    assert await repo.get("none") is None
