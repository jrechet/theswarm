"""Domain tests for Phase G (Scout) entities."""

from __future__ import annotations

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


class TestHashUrl:
    def test_strips_scheme_and_trailing_slash(self):
        a = hash_url("https://example.com/path/")
        b = hash_url("http://example.com/path")
        c = hash_url("example.com/path")
        assert a == b == c

    def test_case_insensitive(self):
        assert hash_url("HTTPS://Example.com/Path") == hash_url("example.com/path")

    def test_different_urls_differ(self):
        assert hash_url("https://a.com") != hash_url("https://b.com")


class TestIntelSource:
    def test_signal_rate_zero_with_no_attempts(self):
        s = IntelSource(id="s", name="HN")
        assert s.signal_rate == 0.0
        assert s.is_healthy is True  # never checked → assume fine

    def test_signal_rate_ratio(self):
        s = IntelSource(id="s", name="HN", success_count=8, error_count=2)
        assert s.signal_rate == 0.8
        assert s.is_healthy is True

    def test_unhealthy_when_errors_dominate(self):
        s = IntelSource(id="s", name="HN", success_count=2, error_count=8)
        assert s.signal_rate == 0.2
        assert s.is_healthy is False

    def test_new_id_prefix(self):
        assert IntelSource.new_id().startswith("src_")


class TestIntelItem:
    def test_cve_is_actionable(self):
        item = IntelItem(id="i", category=IntelCategory.CVE)
        assert item.is_actionable is True

    def test_fyi_is_not_actionable(self):
        item = IntelItem(id="i", category=IntelCategory.FYI)
        assert item.is_actionable is False

    def test_noise_is_not_actionable(self):
        item = IntelItem(id="i", category=IntelCategory.NOISE)
        assert item.is_actionable is False

    def test_has_action_tracks_text(self):
        assert IntelItem(id="i").has_action is False
        assert IntelItem(id="i", action_taken="opened #42").has_action is True

    def test_new_id_prefix(self):
        assert IntelItem.new_id().startswith("intel_")

    def test_default_urgency_is_normal(self):
        assert IntelItem(id="i").urgency == IntelUrgency.NORMAL


class TestIntelCluster:
    def test_size_counts_members(self):
        c = IntelCluster(id="c", member_ids=("a", "b", "c"))
        assert c.size == 3

    def test_empty_cluster_has_zero_size(self):
        assert IntelCluster(id="c").size == 0

    def test_new_id_prefix(self):
        assert IntelCluster.new_id().startswith("cluster_")


class TestValueObjects:
    def test_category_values(self):
        assert IntelCategory.THREAT.value == "threat"
        assert IntelCategory.CVE.value == "cve"
        assert IntelCategory.OPPORTUNITY.value == "opportunity"

    def test_urgency_ordering_constants(self):
        # enum values exist and are distinct
        assert IntelUrgency.CRITICAL.value == "critical"
        assert IntelUrgency.LOW.value == "low"

    def test_source_kinds(self):
        assert SourceKind.RSS.value == "rss"
        assert SourceKind.GH_ADVISORY.value == "gh_advisory"
