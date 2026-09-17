"""Tests for `_cycle_sort_key`, the UTC-normalising sort key for merged cycle timestamps.

SQLite cycles carry aware UTC ISO strings; in-memory tracker `CycleRecord`
entries carry naive local ISO strings. `_list_merged_cycles` must sort both
kinds of timestamp in correct absolute-time order.
"""

from __future__ import annotations

from datetime import datetime, timezone

from theswarm.presentation.web.routes.api import _cycle_sort_key


def test_none_sorts_last():
    assert _cycle_sort_key(None) == datetime.min.replace(tzinfo=timezone.utc)


def test_empty_string_sorts_last():
    assert _cycle_sort_key("") == datetime.min.replace(tzinfo=timezone.utc)


def test_unparseable_string_sorts_last_and_does_not_raise():
    assert _cycle_sort_key("not-a-timestamp") == datetime.min.replace(tzinfo=timezone.utc)


def test_aware_utc_string_converts_to_utc():
    key = _cycle_sort_key("2026-09-17T10:00:00+00:00")
    assert key == datetime(2026, 9, 17, 10, 0, 0, tzinfo=timezone.utc)


def test_naive_local_string_is_treated_as_local_time():
    naive = "2026-09-17T10:00:00"
    key = _cycle_sort_key(naive)
    expected = datetime.fromisoformat(naive).astimezone().astimezone(timezone.utc)
    assert key == expected
    assert key.tzinfo is timezone.utc


def test_naive_and_aware_timestamps_sort_in_correct_relative_order():
    # An aware UTC timestamp that is unambiguously earlier than any local
    # interpretation of the naive timestamp below (local UTC offsets on CI
    # runners are within +/-14h, so a 2-day gap is always decisive).
    earlier_aware = "2026-09-15T00:00:00+00:00"
    later_naive = "2026-09-17T00:00:00"

    entries = [
        (_cycle_sort_key(earlier_aware), "earlier"),
        (_cycle_sort_key(later_naive), "later"),
    ]
    entries.sort(key=lambda pair: pair[0], reverse=True)

    assert [label for _, label in entries] == ["later", "earlier"]


def test_missing_timestamp_sorts_last_among_real_timestamps():
    entries = [
        (_cycle_sort_key("2026-09-17T10:00:00+00:00"), "real"),
        (_cycle_sort_key(None), "missing"),
    ]
    entries.sort(key=lambda pair: pair[0], reverse=True)

    assert [label for _, label in entries] == ["real", "missing"]


def test_result_is_always_aware():
    assert _cycle_sort_key("2026-09-17T10:00:00").tzinfo is not None
    assert _cycle_sort_key("2026-09-17T10:00:00+05:30").tzinfo is not None
