"""Application services for the Scout bounded context (Phase G)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

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
from theswarm.infrastructure.scout import (
    SQLiteIntelClusterRepository,
    SQLiteIntelItemRepository,
    SQLiteIntelSourceRepository,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IntelSourceService:
    """Register upstream intel sources and track their health."""

    def __init__(self, repo: SQLiteIntelSourceRepository) -> None:
        self._repo = repo

    async def register(
        self,
        *,
        name: str,
        kind: SourceKind = SourceKind.CUSTOM,
        url: str = "",
        project_id: str = "",
    ) -> IntelSource:
        source = IntelSource(
            id=IntelSource.new_id(),
            name=name,
            kind=kind,
            url=url,
            project_id=project_id,
        )
        return await self._repo.add(source)

    async def record_success(self, source_id: str) -> IntelSource | None:
        existing = await self._repo.get(source_id)
        if existing is None:
            return None
        updated = replace(
            existing,
            success_count=existing.success_count + 1,
            last_ok_at=_now(),
        )
        await self._repo.update_health(updated)
        return updated

    async def record_error(
        self, source_id: str, *, reason: str,
    ) -> IntelSource | None:
        existing = await self._repo.get(source_id)
        if existing is None:
            return None
        updated = replace(
            existing,
            error_count=existing.error_count + 1,
            last_error=reason,
            last_error_at=_now(),
        )
        await self._repo.update_health(updated)
        return updated

    async def list_all(self) -> list[IntelSource]:
        return await self._repo.list_all()

    async def list_for_project(self, project_id: str) -> list[IntelSource]:
        return await self._repo.list_for_project(project_id)


class IntelFeedService:
    """Ingest, dedupe, classify, and mark actions on intel items."""

    def __init__(self, repo: SQLiteIntelItemRepository) -> None:
        self._repo = repo

    async def ingest(
        self,
        *,
        title: str,
        url: str,
        source_id: str = "",
        summary: str = "",
        category: IntelCategory = IntelCategory.FYI,
        urgency: IntelUrgency = IntelUrgency.NORMAL,
        project_ids: tuple[str, ...] = (),
    ) -> IntelItem | None:
        """Insert an item; returns None if the url was already seen."""
        item = IntelItem(
            id=IntelItem.new_id(),
            source_id=source_id,
            title=title,
            url=url,
            url_hash=hash_url(url),
            summary=summary,
            category=category,
            urgency=urgency,
            project_ids=project_ids,
        )
        return await self._repo.add(item)

    async def classify(
        self,
        *,
        item_id: str,
        category: IntelCategory,
        urgency: IntelUrgency | None = None,
    ) -> IntelItem | None:
        await self._repo.update_category(
            item_id, category=category, urgency=urgency,
        )
        return await self._repo.get(item_id)

    async def mark_action(
        self, *, item_id: str, action_taken: str,
    ) -> IntelItem | None:
        await self._repo.update_action(
            item_id=item_id, action_taken=action_taken,
        )
        return await self._repo.get(item_id)

    async def list_feed(
        self,
        *,
        limit: int = 50,
        category: IntelCategory | None = None,
        project_id: str = "",
    ) -> list[IntelItem]:
        return await self._repo.list_recent(
            limit=limit, category=category, project_id=project_id,
        )

    async def get(self, item_id: str) -> IntelItem | None:
        return await self._repo.get(item_id)


class IntelClusterService:
    """Group related intel items so the feed doesn't show 10 copies of the same story."""

    def __init__(
        self,
        cluster_repo: SQLiteIntelClusterRepository,
        item_repo: SQLiteIntelItemRepository,
    ) -> None:
        self._clusters = cluster_repo
        self._items = item_repo

    async def create(
        self,
        *,
        topic: str,
        summary: str = "",
        member_ids: tuple[str, ...] = (),
    ) -> IntelCluster:
        cluster = IntelCluster(
            id=IntelCluster.new_id(),
            topic=topic,
            summary=summary,
            member_ids=member_ids,
        )
        cluster = await self._clusters.add(cluster)
        for item_id in member_ids:
            await self._items.assign_cluster(item_id, cluster.id)
        return cluster

    async def add_member(
        self, *, cluster_id: str, item_id: str,
    ) -> IntelCluster | None:
        cluster = await self._clusters.get(cluster_id)
        if cluster is None:
            return None
        if item_id in cluster.member_ids:
            return cluster
        new_members = tuple([*cluster.member_ids, item_id])
        await self._clusters.set_members(cluster_id, new_members)
        await self._items.assign_cluster(item_id, cluster_id)
        return replace(cluster, member_ids=new_members)

    async def list_recent(self, *, limit: int = 30) -> list[IntelCluster]:
        return await self._clusters.list_recent(limit=limit)

    async def get(self, cluster_id: str) -> IntelCluster | None:
        return await self._clusters.get(cluster_id)
