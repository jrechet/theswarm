"""Entities for the semantic-memory bounded context (Phase L)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class SemanticMemoryEntry:
    """An indexed memory entry available for semantic retrieval.

    ``enabled`` is opt-in: entries are only returned by search when True.
    Tags are simple string labels; the current retrieval uses tag match +
    substring match rather than embeddings.
    """

    id: str
    project_id: str  # "" = portfolio-wide
    title: str
    content: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    enabled: bool = True
    source: str = ""  # optional pointer to originating artifact
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc),
    )

    @property
    def is_portfolio_wide(self) -> bool:
        return self.project_id == ""

    def matches(self, query: str, tag: str = "") -> bool:
        """Return True if this entry satisfies the query+tag filter.

        Disabled entries never match (opt-in semantics).
        """
        if not self.enabled:
            return False
        if tag and tag not in self.tags:
            return False
        if not query:
            return True
        q = query.casefold()
        haystacks = (self.title, self.content, " ".join(self.tags))
        return any(q in h.casefold() for h in haystacks)
