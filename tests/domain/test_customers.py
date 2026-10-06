"""Customers context — the slug grammar and a member's states (V3 M2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from theswarm.domain.customers.entities import Member
from theswarm.domain.customers.value_objects import Slug, looks_like_cycle_id, slugify

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)


class TestSlug:
    @pytest.mark.parametrize("name,slug", [
        ("Yakoi", "yakoi"),
        ("Maison Verne", "maison-verne"),
        ("  Café  Crème & Co. ", "cafe-creme-co"),
        ("", "customer"),
        ("deadbeefcafe", "deadbeefcafe-c"),  # reads as a cycle id otherwise
        ("x" * 60, "x" * 40),
    ])
    def test_slugify(self, name, slug):
        assert slugify(name) == slug
        Slug(slug)  # and the result is a valid slug

    @pytest.mark.parametrize("bad", ["", "Yakoi", "-yakoi", "ya koi", "a" * 41, "0123456789ab"])
    def test_a_bad_slug_is_refused(self, bad):
        with pytest.raises(ValueError):
            Slug(bad)

    def test_a_cycle_id_is_twelve_hex_characters(self):
        assert looks_like_cycle_id("9f1ef7c952ee")
        assert not looks_like_cycle_id("yakoi") and not looks_like_cycle_id("9f1ef7c952eex")


class TestMember:
    def _member(self, **kw) -> Member:
        return Member(id="m1", customer_id="c1", email="nadia@yakoi.fr", invited_at=NOW, **kw)

    def test_the_states(self):
        fresh = self._member()
        assert fresh.state == "expired" and not fresh.is_active  # no token yet

        invited = fresh.invited("hash", NOW + timedelta(days=14), NOW)
        assert invited.state == "invited" and invited.invitation_open(NOW)
        assert not invited.invitation_open(NOW + timedelta(days=15))
        assert invited.state == "invited" if datetime.now(timezone.utc) < invited.invite_expires_at else "expired"

        active = invited.accepted(NOW + timedelta(hours=1))
        assert active.is_active and active.state == "active"
        assert active.invite_token_hash == "" and active.last_seen_at == NOW + timedelta(hours=1)
        assert not active.invitation_open(NOW + timedelta(hours=2))  # a spent link opens nothing

        gone = active.revoked(NOW + timedelta(days=2))
        assert gone.state == "revoked" and not gone.is_active and gone.invite_token_hash == ""

    def test_the_name_falls_back_to_the_email(self):
        assert self._member().name == "nadia"
        assert self._member(display_name="Nadia Benali").name == "Nadia Benali"

    def test_a_change_returns_a_copy(self):
        before = self._member()
        after = before.seen(NOW)
        assert before.last_seen_at is None and after.last_seen_at == NOW
