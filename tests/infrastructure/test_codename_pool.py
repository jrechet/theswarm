"""Tests for the codename pool loader + deterministic picker."""

from __future__ import annotations

import pytest

from theswarm.infrastructure.agents.codename_pool import (
    CodenameExhausted,
    load_pool,
    pick_codename,
)


class TestLoadPool:
    def test_reads_packaged_pool(self):
        pool = load_pool()
        assert isinstance(pool, tuple)
        # Packaged YAML ships with a moderate list — expect at least 20 names.
        assert len(pool) >= 20
        assert all(isinstance(name, str) and name.strip() == name for name in pool)
        # Dedup invariant — no duplicates after load.
        assert len(set(pool)) == len(pool)

    def test_missing_file_returns_empty(self, tmp_path):
        missing = tmp_path / "no.yaml"
        assert load_pool(missing) == ()

    def test_dedupes_and_strips(self, tmp_path):
        path = tmp_path / "names.yaml"
        path.write_text(
            "names:\n  - Alice\n  - ' Alice '\n  - Bob\n  - ''\n  - 42\n  - Bob\n",
            encoding="utf-8",
        )
        assert load_pool(path) == ("Alice", "Bob")


class TestPickCodename:
    def test_empty_pool_raises(self):
        with pytest.raises(CodenameExhausted):
            pick_codename("p", "po", pool=(), in_use=set())

    def test_deterministic_for_same_inputs(self):
        pool = ("Mei", "Aarav", "Kenji", "Ines", "Oluwa", "Priya")
        a = pick_codename("demo", "po", pool, in_use=set())
        b = pick_codename("demo", "po", pool, in_use=set())
        assert a == b
        assert a in pool

    def test_different_roles_pick_different_offsets(self):
        # Probabilistic but with 6 names and different sha256 offsets this
        # should land on at least two distinct codenames across the 4 core roles.
        pool = ("Mei", "Aarav", "Kenji", "Ines", "Oluwa", "Priya")
        picks = {
            role: pick_codename("demo", role, pool, in_use=set())
            for role in ("po", "techlead", "dev", "qa")
        }
        assert len(set(picks.values())) >= 2

    def test_skips_in_use(self):
        pool = ("Mei", "Aarav", "Kenji")
        first = pick_codename("demo", "po", pool, in_use=set())
        second = pick_codename("demo", "po", pool, in_use={first})
        assert second != first
        assert second in pool

    def test_exhausted_pool_raises(self):
        pool = ("Mei", "Aarav")
        with pytest.raises(CodenameExhausted):
            pick_codename("demo", "po", pool, in_use={"Mei", "Aarav"})
