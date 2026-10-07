"""SQLite repositories of the Customers context (migration v033)."""

from __future__ import annotations

from datetime import datetime

import aiosqlite

from theswarm.domain.customers.entities import Customer, Member


def _iso(moment: datetime | None) -> str:
    return moment.isoformat() if moment is not None else ""


def _moment(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


class SQLiteCustomerRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def get(self, customer_id: str) -> Customer | None:
        cursor = await self._db.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
        row = await cursor.fetchone()
        return self._row(row) if row else None

    async def get_by_slug(self, slug: str) -> Customer | None:
        cursor = await self._db.execute("SELECT * FROM customers WHERE slug = ?", (slug,))
        row = await cursor.fetchone()
        return self._row(row) if row else None

    async def list_all(self) -> list[Customer]:
        cursor = await self._db.execute("SELECT * FROM customers ORDER BY created_at, name")
        return [self._row(r) for r in await cursor.fetchall()]

    async def save(self, customer: Customer) -> None:
        await self._db.execute(
            "INSERT OR REPLACE INTO customers (id, slug, name, created_at) VALUES (?, ?, ?, ?)",
            (customer.id, customer.slug, customer.name, customer.created_at.isoformat()),
        )
        await self._db.commit()

    async def delete(self, customer_id: str) -> None:
        await self._db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        await self._db.commit()

    @staticmethod
    def _row(row) -> Customer:
        return Customer(id=row["id"], slug=row["slug"], name=row["name"],
                        created_at=datetime.fromisoformat(row["created_at"]))


class SQLiteMemberRepository:
    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    async def get(self, member_id: str) -> Member | None:
        cursor = await self._db.execute("SELECT * FROM members WHERE id = ?", (member_id,))
        row = await cursor.fetchone()
        return self._row(row) if row else None

    async def list_for_customer(self, customer_id: str) -> list[Member]:
        cursor = await self._db.execute(
            "SELECT * FROM members WHERE customer_id = ? ORDER BY invited_at", (customer_id,),
        )
        return [self._row(r) for r in await cursor.fetchall()]

    async def find_by_email(self, customer_id: str, email: str) -> Member | None:
        cursor = await self._db.execute(
            "SELECT * FROM members WHERE customer_id = ? AND email = ?", (customer_id, email.strip().lower()),
        )
        row = await cursor.fetchone()
        return self._row(row) if row else None

    async def find_by_github_login(self, login: str) -> Member | None:
        cursor = await self._db.execute(
            "SELECT * FROM members WHERE github_login = ? COLLATE NOCASE AND github_login != '' "
            "AND revoked_at = '' ORDER BY accepted_at DESC LIMIT 1", (login,),
        )
        row = await cursor.fetchone()
        return self._row(row) if row else None

    async def find_by_invite_token_hash(self, token_hash: str) -> Member | None:
        if not token_hash:
            return None
        cursor = await self._db.execute(
            "SELECT * FROM members WHERE invite_token_hash = ?", (token_hash,),
        )
        row = await cursor.fetchone()
        return self._row(row) if row else None

    async def save(self, member: Member) -> None:
        # Upsert by id only: a second row for the same email of a customer is a
        # programming error and raises (the unique index), never a silent
        # replacement of the member who was there.
        await self._db.execute(
            """INSERT INTO members
               (id, customer_id, email, display_name, github_login, invited_at,
                invite_token_hash, invite_expires_at, accepted_at, last_seen_at, revoked_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 customer_id = excluded.customer_id, email = excluded.email,
                 display_name = excluded.display_name, github_login = excluded.github_login,
                 invited_at = excluded.invited_at, invite_token_hash = excluded.invite_token_hash,
                 invite_expires_at = excluded.invite_expires_at, accepted_at = excluded.accepted_at,
                 last_seen_at = excluded.last_seen_at, revoked_at = excluded.revoked_at""",
            (member.id, member.customer_id, member.email.strip().lower(), member.display_name,
             member.github_login, member.invited_at.isoformat(), member.invite_token_hash,
             _iso(member.invite_expires_at), _iso(member.accepted_at), _iso(member.last_seen_at),
             _iso(member.revoked_at)),
        )
        await self._db.commit()

    @staticmethod
    def _row(row) -> Member:
        return Member(
            id=row["id"], customer_id=row["customer_id"], email=row["email"],
            display_name=row["display_name"], github_login=row["github_login"],
            invited_at=datetime.fromisoformat(row["invited_at"]),
            invite_token_hash=row["invite_token_hash"],
            invite_expires_at=_moment(row["invite_expires_at"]),
            accepted_at=_moment(row["accepted_at"]),
            last_seen_at=_moment(row["last_seen_at"]),
            revoked_at=_moment(row["revoked_at"]),
        )
