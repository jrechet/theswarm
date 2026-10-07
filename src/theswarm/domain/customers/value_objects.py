"""Value objects of the Customers context."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_CYCLE_ID_RE = re.compile(r"^[0-9a-f]{12}$")
SLUG_MAX = 40


@dataclass(frozen=True)
class Slug:
    """A customer's URL name: lower case, letters, digits and dashes.

    Never twelve hex characters — that is the shape of a cycle id, and
    ``/c/{slug}`` must stay unambiguous beside ``/c/{cycle_id}`` until the
    theater moves to ``/cycles/`` (M4).
    """

    value: str

    def __post_init__(self) -> None:
        if not _SLUG_RE.match(self.value):
            raise ValueError(f"Invalid slug: {self.value!r} (lower case, letters, digits, dashes, 40 at most)")
        if _CYCLE_ID_RE.match(self.value):
            raise ValueError(f"Invalid slug: {self.value!r} reads as a cycle id")

    def __str__(self) -> str:
        return self.value


def looks_like_cycle_id(text: str) -> bool:
    return bool(_CYCLE_ID_RE.match(text))


def slugify(name: str) -> str:
    """A slug from a company name: 'Maison Verne' → 'maison-verne'.

    Accents are stripped, runs of other characters become one dash, a
    result that reads as a cycle id gets a ``-c`` suffix. Empty names give
    ``customer``.
    """
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")[:SLUG_MAX].strip("-")
    if not slug:
        slug = "customer"
    if looks_like_cycle_id(slug):
        slug = f"{slug}-c"
    return slug
