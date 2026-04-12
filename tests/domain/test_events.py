"""Tests for domain/events base class."""

from __future__ import annotations

from theswarm.domain.events import DomainEvent


class TestDomainEvent:
    def test_auto_fields(self):
        e = DomainEvent()
        assert len(e.event_id) == 12
        assert e.occurred_at is not None

    def test_unique_ids(self):
        events = [DomainEvent() for _ in range(100)]
        ids = {e.event_id for e in events}
        assert len(ids) == 100

    def test_frozen(self):
        import pytest
        e = DomainEvent()
        with pytest.raises(AttributeError):
            e.event_id = "x"  # type: ignore[misc]
