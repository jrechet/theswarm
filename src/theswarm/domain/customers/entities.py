"""Entities of the Customers context (frozen; every change returns a copy)."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Customer:
    """A company the owner works for. Its members see it and nothing else."""

    id: str
    slug: str
    name: str
    created_at: datetime = field(default_factory=_now)

    @property
    def initial(self) -> str:
        return (self.name[:1] or "?").upper()


@dataclass(frozen=True)
class Member:
    """A person of a customer, invited by email.

    The invitation is a link: its token is kept hashed and shown to the
    owner once. Accepting sets ``accepted_at`` and clears the token. A
    revoked member keeps its row (who was there) but no door.
    """

    id: str
    customer_id: str
    email: str
    display_name: str = ""
    github_login: str = ""
    invited_at: datetime = field(default_factory=_now)
    invite_token_hash: str = ""
    invite_expires_at: datetime | None = None
    accepted_at: datetime | None = None
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def name(self) -> str:
        return self.display_name or self.email.partition("@")[0]

    @property
    def is_active(self) -> bool:
        """Accepted and not revoked: may sign in."""
        return self.accepted_at is not None and self.revoked_at is None

    def invitation_open(self, now: datetime | None = None) -> bool:
        """Not accepted, not revoked, a token that has not expired."""
        now = now or _now()
        return (self.accepted_at is None and self.revoked_at is None
                and bool(self.invite_token_hash)
                and (self.invite_expires_at is None or now < self.invite_expires_at))

    @property
    def state(self) -> str:
        """One word for the settings page: active, invited, expired, revoked."""
        if self.revoked_at is not None:
            return "revoked"
        if self.accepted_at is not None:
            return "active"
        return "invited" if self.invitation_open() else "expired"

    def invited(self, token_hash: str, expires_at: datetime, now: datetime | None = None) -> Member:
        return replace(self, invite_token_hash=token_hash, invite_expires_at=expires_at,
                       invited_at=now or _now(), accepted_at=None, revoked_at=None)

    def accepted(self, now: datetime | None = None) -> Member:
        now = now or _now()
        return replace(self, accepted_at=now, last_seen_at=now, invite_token_hash="", invite_expires_at=None)

    def revoked(self, now: datetime | None = None) -> Member:
        return replace(self, revoked_at=now or _now(), invite_token_hash="", invite_expires_at=None)

    def seen(self, now: datetime | None = None) -> Member:
        return replace(self, last_seen_at=now or _now())
