"""Phase G infrastructure tests for Scout SQLite repositories."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from theswarm.domain.scout.entities import (
    IntelCluster,
    IntelItem,
    IntelSource,
    hash_url,
)
from theswarm.domain.scout.value_objects import (
    IntelCategory,
    IntelUrgency,
    SourceKind,
)
from theswarm.infrastructure.persistence.sqlite_repos import init_db
from theswarm.infrastructure.scout import (
    SQLiteIntelClusterRepository,
    SQLiteIntelItemRepository,
    SQLiteIntelSourceRepository,
)


@pytest.fixture()
async def db(tmp_path):
    conn = await init_db(str(tmp_path / "scout.db"))
    yield conn
    await conn.close()


class TestIntelSourceRepoIntegration:
    async def test_add_and_list(self, db):
        repo = SQLiteIntelSourceRepository(db)
        await repo.add(IntelSource(
            id="s1", name="HN", kind=SourceKind.HN, url="https://news.ycombinator.com",
        ))
        await repo.add(IntelSource(
            id="s2", name="GH Adv", kind=SourceKind.GH_ADVISORY,
            url="https://github.com/advisories",
        ))
        await repo.add(IntelSource(
            id="s3", name="Proj RSS", kind=SourceKind.RSS,
            url="https://example.com/rss", project_id="p1",
        ))

        all_sources = await repo.list_all()
        assert len(all_sources) == 3

        p1_sources = await repo.list_for_project("p1")
        # portfolio + project-scoped
        assert len(p1_sources) == 3

    async def test_update_health(self, db):
        repo = SQLiteIntelSourceRepository(db)
        await repo.add(IntelSource(id="s1", name="HN"))
        src = await repo.get("s1")
        assert src is not None

        now = datetime.now(timezone.utc)
        updated = replace(
            src, success_count=5, error_count=1, last_ok_at=now,
        )
        await repo.update_health(updated)

        got = await repo.get("s1")
        assert got is not None
        assert got.success_count == 5
        assert got.error_count == 1
        assert got.signal_rate == round(5 / 6, 3)


class TestIntelItemRepoIntegration:
    async def test_add_and_dedupe_by_url_hash(self, db):
        repo = SQLiteIntelItemRepository(db)
        url = "https://example.com/article"
        first = IntelItem(
            id="i1", title="first", url=url, url_hash=hash_url(url),
            category=IntelCategory.OPPORTUNITY,
        )
        result1 = await repo.add(first)
        assert result1 is not None

        # try to add a second with same url_hash → should return None
        dup = IntelItem(
            id="i2", title="dup", url=url, url_hash=hash_url(url),
        )
        result2 = await repo.add(dup)
        assert result2 is None

        got = await repo.get_by_url_hash(hash_url(url))
        assert got is not None
        assert got.id == "i1"

    async def test_update_action_and_category(self, db):
        repo = SQLiteIntelItemRepository(db)
        item = IntelItem(
            id="i1", title="t", url="http://x", url_hash="h1",
            category=IntelCategory.FYI,
        )
        await repo.add(item)

        await repo.update_action(item_id="i1", action_taken="opened issue #42")
        await repo.update_category(
            "i1", category=IntelCategory.THREAT, urgency=IntelUrgency.HIGH,
        )

        got = await repo.get("i1")
        assert got is not None
        assert got.action_taken == "opened issue #42"
        assert got.has_action is True
        assert got.category == IntelCategory.THREAT
        assert got.urgency == IntelUrgency.HIGH

    async def test_list_recent_filtering(self, db):
        repo = SQLiteIntelItemRepository(db)
        await repo.add(IntelItem(
            id="a", title="a", url="http://a", url_hash="a",
            category=IntelCategory.CVE,
            project_ids=("proj1",),
        ))
        await repo.add(IntelItem(
            id="b", title="b", url="http://b", url_hash="b",
            category=IntelCategory.OPPORTUNITY,
            project_ids=("proj2",),
        ))
        await repo.add(IntelItem(
            id="c", title="c", url="http://c", url_hash="c",
            category=IntelCategory.FYI,
            # no project_ids → portfolio-wide
        ))

        cve_items = await repo.list_recent(category=IntelCategory.CVE)
        assert len(cve_items) == 1
        assert cve_items[0].id == "a"

        proj1_items = await repo.list_recent(project_id="proj1")
        # matches proj1 + portfolio (c)
        assert len(proj1_items) == 2
        ids = {it.id for it in proj1_items}
        assert ids == {"a", "c"}

    async def test_assign_cluster(self, db):
        repo = SQLiteIntelItemRepository(db)
        await repo.add(IntelItem(
            id="x", title="t", url="http://x", url_hash="x",
        ))
        await repo.assign_cluster("x", "cluster_42")
        got = await repo.get("x")
        assert got is not None
        assert got.cluster_id == "cluster_42"


class TestIntelClusterRepoIntegration:
    async def test_add_and_set_members(self, db):
        repo = SQLiteIntelClusterRepository(db)
        c = IntelCluster(id="c1", topic="Python 3.13", member_ids=("a",))
        await repo.add(c)

        await repo.set_members("c1", ("a", "b", "c"))
        got = await repo.get("c1")
        assert got is not None
        assert got.size == 3

    async def test_list_recent(self, db):
        repo = SQLiteIntelClusterRepository(db)
        await repo.add(IntelCluster(id="c1", topic="first"))
        await repo.add(IntelCluster(id="c2", topic="second"))
        listed = await repo.list_recent()
        assert len(listed) == 2
        assert listed[0].topic == "second"
