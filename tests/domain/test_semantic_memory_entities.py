"""Phase L domain tests — semantic memory."""

from __future__ import annotations

from theswarm.domain.semantic_memory.entities import SemanticMemoryEntry


class TestSemanticMemoryEntry:
    def test_empty_project_id_is_portfolio_wide(self):
        e = SemanticMemoryEntry(id="e1", project_id="", title="x", content="")
        assert e.is_portfolio_wide

    def test_project_scoped_not_portfolio_wide(self):
        e = SemanticMemoryEntry(id="e1", project_id="p", title="x", content="")
        assert not e.is_portfolio_wide

    def test_disabled_entry_never_matches(self):
        e = SemanticMemoryEntry(
            id="e1", project_id="", title="auth flow", content="jwt rotation",
            enabled=False,
        )
        assert not e.matches("auth")

    def test_case_insensitive_substring_match(self):
        e = SemanticMemoryEntry(
            id="e1", project_id="", title="Auth Flow", content="JWT ROTATION",
        )
        assert e.matches("auth")
        assert e.matches("jwt")

    def test_tag_filter_requires_presence(self):
        e = SemanticMemoryEntry(
            id="e1", project_id="", title="x", content="",
            tags=("security",),
        )
        assert e.matches("", tag="security")
        assert not e.matches("", tag="design")

    def test_empty_query_returns_all_enabled(self):
        e = SemanticMemoryEntry(id="e1", project_id="", title="x", content="")
        assert e.matches("")

    def test_query_matches_tag_text(self):
        e = SemanticMemoryEntry(
            id="e1", project_id="", title="x", content="",
            tags=("incident",),
        )
        assert e.matches("incident")
