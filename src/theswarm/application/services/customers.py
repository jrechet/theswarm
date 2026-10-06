"""Customers, their projects and their members (V3 M2).

The owner creates a customer, assigns it repositories, invites people by
email. An invitation is a link the owner sends themselves — no SMTP, no
new dependency: its token is shown once, kept hashed, good for fourteen
days and one use. Accepting it is the member's door; a member sees their
customer and nothing else (`actor_may`).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from theswarm.domain.customers.entities import Customer, Member
from theswarm.domain.customers.ports import CustomerRepository, MemberRepository
from theswarm.domain.customers.value_objects import Slug, slugify
from theswarm.domain.projects.entities import Project
from theswarm.domain.projects.ports import ProjectRepository
from theswarm.domain.projects.value_objects import RepoUrl

INVITATION_DAYS = 14
INTERNAL = "internal"


class CustomerError(ValueError):
    """A request the owner made that cannot be honoured, with the reason."""


@dataclass(frozen=True)
class Actor:
    """Who a request is: the owner (login or the access key) or a member."""

    kind: str  # "owner" | "member"
    login: str = ""
    member_id: str = ""
    customer_id: str = ""

    @property
    def is_owner(self) -> bool:
        return self.kind == "owner"


def actor_may(actor: Actor | None, customer_id: str) -> bool:
    """The owner passes everywhere; a member only inside their customer."""
    if actor is None:
        return False
    if actor.is_owner:
        return True
    return actor.kind == "member" and bool(customer_id) and actor.customer_id == customer_id


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


class CustomerService:
    def __init__(self, customers: CustomerRepository, members: MemberRepository,
                 projects: ProjectRepository) -> None:
        self._customers = customers
        self._members = members
        self._projects = projects

    # ── Customers ────────────────────────────────────────────────────

    async def create(self, name: str) -> Customer:
        name = " ".join(name.split())
        if not name:
            raise CustomerError("A customer needs a name.")
        base = slugify(name)
        slug, n = base, 1
        while await self._customers.get_by_slug(slug) is not None:
            n += 1
            slug = f"{base[:Slug.__annotations__ and 36]}-{n}"
        customer = Customer(id=_new_id(), slug=str(Slug(slug)), name=name, created_at=_now())
        await self._customers.save(customer)
        return customer

    async def by_slug(self, slug: str) -> Customer | None:
        return await self._customers.get_by_slug(slug)

    async def list_all(self) -> list[Customer]:
        return await self._customers.list_all()

    # ── Projects ─────────────────────────────────────────────────────

    async def projects_of(self, customer: Customer) -> list[Project]:
        return await self._projects.list_for_customer(customer.id)

    async def assign_project(self, full_name: str, customer: Customer) -> Project:
        """Give a repository to a customer, registering it if it is new."""
        repo = RepoUrl(full_name.strip())  # raises ValueError on a bad name
        for project in await self._projects.list_all():
            if str(project.repo) == str(repo):
                moved = project.with_customer(customer.id)
                await self._projects.save(moved)
                return moved
        project = Project(id=str(repo).replace("/", "-"), repo=repo, customer_id=customer.id)
        await self._projects.save(project)
        return project

    # ── Members ──────────────────────────────────────────────────────

    async def members_of(self, customer: Customer) -> list[Member]:
        return await self._members.list_for_customer(customer.id)

    async def invite(self, customer: Customer, email: str, display_name: str = "",
                     now: datetime | None = None) -> tuple[Member, str]:
        """Invite (or re-invite) an email: the member and the token, shown once."""
        now = now or _now()
        email = email.strip().lower()
        if "@" not in email or email.startswith("@") or email.endswith("@"):
            raise CustomerError("That is not an email address.")
        token = secrets.token_urlsafe(32)
        existing = await self._members.find_by_email(customer.id, email)
        if existing is not None and existing.is_active:
            raise CustomerError(f"{existing.name} is already a member.")
        member = existing or Member(id=_new_id(), customer_id=customer.id, email=email,
                                    display_name=display_name.strip(), invited_at=now)
        if display_name.strip():
            member = Member(**{**member.__dict__, "display_name": display_name.strip()})
        member = member.invited(hash_token(token), now + timedelta(days=INVITATION_DAYS), now)
        await self._members.save(member)
        return member, token

    async def accept(self, token: str, now: datetime | None = None) -> Member | None:
        """The invitation's door: the member once, None for a bad or spent link."""
        now = now or _now()
        member = await self._members.find_by_invite_token_hash(hash_token(token))
        if member is None or not member.invitation_open(now):
            return None
        accepted = member.accepted(now)
        await self._members.save(accepted)
        return accepted

    async def revoke(self, member_id: str, now: datetime | None = None) -> Member | None:
        member = await self._members.get(member_id)
        if member is None:
            return None
        revoked = member.revoked(now or _now())
        await self._members.save(revoked)
        return revoked

    async def seen(self, member_id: str, now: datetime | None = None) -> None:
        member = await self._members.get(member_id)
        if member is not None:
            await self._members.save(member.seen(now or _now()))

    async def member(self, member_id: str) -> Member | None:
        return await self._members.get(member_id)

    async def member_by_github_login(self, login: str) -> Member | None:
        return await self._members.find_by_github_login(login)

    async def actor_for_member(self, member_id: str) -> Actor | None:
        """The actor a member session stands for — None once revoked."""
        member = await self._members.get(member_id)
        if member is None or not member.is_active:
            return None
        return Actor(kind="member", login=member.name, member_id=member.id, customer_id=member.customer_id)
