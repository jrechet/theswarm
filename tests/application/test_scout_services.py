"""Phase G application-layer tests for Scout services."""

from __future__ import annotations

import pytest

from theswarm.application.services.scout import (
    IntelClusterService,
    IntelFeedService,
    IntelSourceService,
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
    conn = await init_db(str(tmp_path / "scout_services.db"))
    yield conn
    await conn.close()


class TestIntelSourceService:
    async def test_register_and_list(self, db):
        svc = IntelSourceService(SQLiteIntelSourceRepository(db))
        await svc.register(name="HN", kind=SourceKind.HN, url="https://news.yc")
        await svc.register(
            name="Proj feed", kind=SourceKind.RSS, url="https://ex.com/rss",
            project_id="p1",
        )
        all_sources = await svc.list_all()
        assert len(all_sources) == 2

        p1 = await svc.list_for_project("p1")
        assert len(p1) == 2  # both: portfolio HN + project-scoped

    async def test_record_success_and_error(self, db):
        svc = IntelSourceService(SQLiteIntelSourceRepository(db))
        src = await svc.register(name="HN", kind=SourceKind.HN)

        ok = await svc.record_success(src.id)
        assert ok is not None
        assert ok.success_count == 1
        assert ok.last_ok_at is not None

        err = await svc.record_error(src.id, reason="timeout")
        assert err is not None
        assert err.error_count == 1
        assert err.last_error == "timeout"

    async def test_record_on_missing_source_returns_none(self, db):
        svc = IntelSourceService(SQLiteIntelSourceRepository(db))
        assert await svc.record_success("missing") is None
        assert await svc.record_error("missing", reason="x") is None


class TestIntelFeedService:
    async def test_ingest_and_dedupe(self, db):
        svc = IntelFeedService(SQLiteIntelItemRepository(db))
        first = await svc.ingest(
            title="CVE in Python", url="https://example.com/cve-1",
            category=IntelCategory.CVE, urgency=IntelUrgency.HIGH,
        )
        assert first is not None

        dup = await svc.ingest(
            title="repost", url="https://example.com/cve-1",
        )
        assert dup is None  # silent dedup by url_hash

    async def test_classify_updates_category_and_urgency(self, db):
        svc = IntelFeedService(SQLiteIntelItemRepository(db))
        item = await svc.ingest(
            title="maybe noise", url="http://x",
            category=IntelCategory.FYI,
        )
        assert item is not None
        updated = await svc.classify(
            item_id=item.id,
            category=IntelCategory.THREAT,
            urgency=IntelUrgency.CRITICAL,
        )
        assert updated is not None
        assert updated.category == IntelCategory.THREAT
        assert updated.urgency == IntelUrgency.CRITICAL
        assert updated.is_actionable is True

    async def test_mark_action(self, db):
        svc = IntelFeedService(SQLiteIntelItemRepository(db))
        item = await svc.ingest(
            title="bump dep", url="http://pkg/x",
            category=IntelCategory.OPPORTUNITY,
        )
        assert item is not None
        acted = await svc.mark_action(
            item_id=item.id, action_taken="opened PR #7",
        )
        assert acted is not None
        assert acted.action_taken == "opened PR #7"
        assert acted.has_action is True

    async def test_list_feed_filters_by_category_and_project(self, db):
        svc = IntelFeedService(SQLiteIntelItemRepository(db))
        await svc.ingest(
            title="a", url="http://a",
            category=IntelCategory.CVE, project_ids=("p1",),
        )
        await svc.ingest(
            title="b", url="http://b",
            category=IntelCategory.FYI, project_ids=("p2",),
        )
        await svc.ingest(
            title="c", url="http://c",
            category=IntelCategory.OPPORTUNITY,
            # portfolio-wide
        )

        cves = await svc.list_feed(category=IntelCategory.CVE)
        assert len(cves) == 1

        p1 = await svc.list_feed(project_id="p1")
        ids = {it.title for it in p1}
        assert ids == {"a", "c"}


class TestIntelClusterService:
    async def test_create_with_members_assigns_cluster_id(self, db):
        items_repo = SQLiteIntelItemRepository(db)
        feed = IntelFeedService(items_repo)
        a = await feed.ingest(title="a", url="http://a")
        b = await feed.ingest(title="b", url="http://b")
        assert a is not None and b is not None

        svc = IntelClusterService(
            SQLiteIntelClusterRepository(db), items_repo,
        )
        cluster = await svc.create(
            topic="Python 3.13", member_ids=(a.id, b.id),
        )
        assert cluster.size == 2

        got_a = await feed.get(a.id)
        assert got_a is not None
        assert got_a.cluster_id == cluster.id

    async def test_add_member_is_idempotent(self, db):
        items_repo = SQLiteIntelItemRepository(db)
        feed = IntelFeedService(items_repo)
        a = await feed.ingest(title="a", url="http://a")
        assert a is not None

        svc = IntelClusterService(
            SQLiteIntelClusterRepository(db), items_repo,
        )
        cluster = await svc.create(topic="T")
        updated = await svc.add_member(cluster_id=cluster.id, item_id=a.id)
        again = await svc.add_member(cluster_id=cluster.id, item_id=a.id)
        assert updated is not None and again is not None
        assert again.size == 1

    async def test_add_member_missing_cluster_returns_none(self, db):
        items_repo = SQLiteIntelItemRepository(db)
        svc = IntelClusterService(
            SQLiteIntelClusterRepository(db), items_repo,
        )
        assert await svc.add_member(cluster_id="none", item_id="x") is None
