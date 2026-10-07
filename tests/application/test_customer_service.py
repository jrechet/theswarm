"""The customer service: create, assign a repository, invite, accept, revoke (V3 M2).

The first customer is real: TLphone, project espace client
(jrechet/espace-client) — the owner, 2026-10-06.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from theswarm.application.services.customers import (
    INTERNAL,
    Actor,
    CustomerError,
    CustomerService,
    actor_may,
    hash_token,
)
from theswarm.infrastructure.persistence.customer_repo import (
    SQLiteCustomerRepository,
    SQLiteMemberRepository,
)
from theswarm.infrastructure.persistence.sqlite_repos import SQLiteProjectRepository, init_db

NOW = datetime(2026, 10, 6, 14, 0, tzinfo=timezone.utc)


@pytest.fixture()
async def service(tmp_path):
    conn = await init_db(str(tmp_path / "t.db"))
    svc = CustomerService(SQLiteCustomerRepository(conn), SQLiteMemberRepository(conn),
                          SQLiteProjectRepository(conn))
    yield svc
    await conn.close()


class TestCustomers:
    async def test_create_gives_a_slug_and_lists_after_internal(self, service):
        tl = await service.create("  TLphone ")
        assert tl.name == "TLphone" and tl.slug == "tlphone" and tl.initial == "T"
        assert [c.slug for c in await service.list_all()] == ["internal", "tlphone"]
        assert (await service.by_slug("tlphone")).id == tl.id

    async def test_a_second_customer_of_the_same_name_gets_a_numbered_slug(self, service):
        await service.create("TLphone")
        again = await service.create("TLphone")
        assert again.slug == "tlphone-2"

    async def test_a_nameless_customer_is_refused(self, service):
        with pytest.raises(CustomerError):
            await service.create("   ")


class TestProjects:
    async def test_assign_registers_a_new_repository_under_the_customer(self, service):
        tl = await service.create("TLphone")
        project = await service.assign_project("jrechet/espace-client", tl)
        assert project.customer_id == tl.id and str(project.repo) == "jrechet/espace-client"
        assert [str(p.repo) for p in await service.projects_of(tl)] == ["jrechet/espace-client"]

    async def test_assign_moves_a_registered_repository(self, service):
        tl = await service.create("TLphone")
        internal = await service.by_slug(INTERNAL)
        before = await service.assign_project("jrechet/espace-client", internal)
        moved = await service.assign_project("jrechet/espace-client", tl)
        assert moved.id == before.id and moved.customer_id == tl.id
        assert await service.projects_of(internal) == []

    async def test_a_bad_repository_name_is_refused(self, service):
        tl = await service.create("TLphone")
        with pytest.raises(ValueError):
            await service.assign_project("not a repo", tl)


class TestMembers:
    async def test_invite_accept_and_the_link_is_spent(self, service):
        tl = await service.create("TLphone")
        member, token = await service.invite(tl, " Nadia@TLphone.fr ", "Nadia", now=NOW)
        assert member.email == "nadia@tlphone.fr" and member.name == "Nadia"
        assert member.state == "invited" and member.invite_token_hash == hash_token(token)
        assert member.invite_expires_at == NOW + timedelta(days=14)
        assert len(token) >= 40

        assert await service.accept("not-the-token", now=NOW) is None
        accepted = await service.accept(token, now=NOW + timedelta(hours=2))
        assert accepted is not None and accepted.is_active and accepted.id == member.id
        assert await service.accept(token, now=NOW + timedelta(hours=3)) is None  # one use

        actor = await service.actor_for_member(member.id)
        assert actor == Actor(kind="member", login="Nadia", member_id=member.id, customer_id=tl.id)

    async def test_an_expired_link_opens_nothing(self, service):
        tl = await service.create("TLphone")
        _, token = await service.invite(tl, "nadia@tlphone.fr", now=NOW)
        assert await service.accept(token, now=NOW + timedelta(days=15)) is None

    async def test_re_inviting_an_invited_email_renews_the_link(self, service):
        tl = await service.create("TLphone")
        first, token1 = await service.invite(tl, "nadia@tlphone.fr", now=NOW)
        second, token2 = await service.invite(tl, "nadia@tlphone.fr", "Nadia B.", now=NOW + timedelta(days=1))
        assert second.id == first.id and second.display_name == "Nadia B." and token1 != token2
        assert await service.accept(token1, now=NOW + timedelta(days=2)) is None
        assert (await service.accept(token2, now=NOW + timedelta(days=2))).is_active
        assert len(await service.members_of(tl)) == 1

    async def test_an_active_member_is_not_invited_twice(self, service):
        tl = await service.create("TLphone")
        _, token = await service.invite(tl, "nadia@tlphone.fr", now=NOW)
        await service.accept(token, now=NOW)
        with pytest.raises(CustomerError):
            await service.invite(tl, "nadia@tlphone.fr", now=NOW)

    async def test_revoked_means_no_door(self, service):
        tl = await service.create("TLphone")
        member, token = await service.invite(tl, "nadia@tlphone.fr", now=NOW)
        await service.accept(token, now=NOW)
        await service.revoke(member.id, now=NOW + timedelta(days=1))
        assert await service.actor_for_member(member.id) is None
        assert (await service.member(member.id)).state == "revoked"

    async def test_an_email_that_is_not_one_is_refused(self, service):
        tl = await service.create("TLphone")
        for bad in ("nadia", "@tlphone.fr", "nadia@"):
            with pytest.raises(CustomerError):
                await service.invite(tl, bad, now=NOW)

    async def test_seen_moves_the_clock(self, service):
        tl = await service.create("TLphone")
        member, token = await service.invite(tl, "nadia@tlphone.fr", now=NOW)
        await service.accept(token, now=NOW)
        await service.seen(member.id, now=NOW + timedelta(hours=5))
        assert (await service.member(member.id)).last_seen_at == NOW + timedelta(hours=5)


class TestActorMay:
    def test_the_owner_passes_a_member_stays_home(self):
        owner = Actor(kind="owner", login="jrechet")
        nadia = Actor(kind="member", login="Nadia", member_id="m1", customer_id="c1")
        assert actor_may(owner, "c1") and actor_may(owner, "c2")
        assert actor_may(nadia, "c1") and not actor_may(nadia, "c2") and not actor_may(nadia, "")
        assert not actor_may(None, "c1")
