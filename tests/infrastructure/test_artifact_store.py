"""Tests for LocalArtifactStore."""

from __future__ import annotations

import pytest

from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.reporting.value_objects import Artifact, ArtifactType
from theswarm.infrastructure.recording.artifact_store import LocalArtifactStore


@pytest.fixture
def store(tmp_path):
    return LocalArtifactStore(base_dir=str(tmp_path / "artifacts"))


@pytest.fixture
def cycle_id():
    return CycleId("cycle-001")


def _make_artifact(
    art_type: ArtifactType = ArtifactType.SCREENSHOT,
    label: str = "homepage",
    path: str = "",
) -> Artifact:
    return Artifact(type=art_type, label=label, path=path)


class TestSave:
    async def test_save_screenshot(self, store, cycle_id):
        art = _make_artifact()
        path = await store.save(cycle_id, art, b"PNG_DATA")
        assert "screenshot" in path
        assert "homepage" in path
        assert path.endswith(".png")

    async def test_save_creates_file(self, store, cycle_id, tmp_path):
        art = _make_artifact()
        rel_path = await store.save(cycle_id, art, b"PNG_DATA")
        full = tmp_path / "artifacts" / rel_path
        assert full.exists()
        assert full.read_bytes() == b"PNG_DATA"

    async def test_save_video(self, store, cycle_id):
        art = _make_artifact(ArtifactType.VIDEO, "demo-recording")
        path = await store.save(cycle_id, art, b"WEBM")
        assert path.endswith(".webm")
        assert "video" in path

    async def test_save_diff(self, store, cycle_id):
        art = _make_artifact(ArtifactType.DIFF, "changes")
        path = await store.save(cycle_id, art, b"diff content")
        assert path.endswith(".diff")

    async def test_save_log(self, store, cycle_id):
        art = _make_artifact(ArtifactType.LOG, "build-output")
        path = await store.save(cycle_id, art, b"log lines")
        assert path.endswith(".log")

    async def test_save_avoids_overwrite(self, store, cycle_id):
        art = _make_artifact(label="same-name")
        p1 = await store.save(cycle_id, art, b"first")
        p2 = await store.save(cycle_id, art, b"second")
        assert p1 != p2

    async def test_save_sanitizes_label(self, store, cycle_id):
        art = _make_artifact(label="path/with spaces")
        path = await store.save(cycle_id, art, b"data")
        assert "/" not in path.split("/")[-1].replace("_", "")
        assert " " not in path

    async def test_save_empty_label(self, store, cycle_id):
        art = _make_artifact(label="")
        path = await store.save(cycle_id, art, b"data")
        assert "artifact" in path


class TestGetUrl:
    async def test_get_url_existing(self, store, cycle_id):
        art = _make_artifact()
        rel_path = await store.save(cycle_id, art, b"data")
        url = await store.get_url(rel_path)
        assert url.endswith(rel_path)

    async def test_get_url_missing(self, store):
        url = await store.get_url("nonexistent/file.png")
        assert url == "/artifacts/nonexistent/file.png"


class TestListByCycle:
    async def test_list_empty(self, store, cycle_id):
        result = await store.list_by_cycle(cycle_id)
        assert result == []

    async def test_list_after_save(self, store, cycle_id):
        await store.save(cycle_id, _make_artifact(ArtifactType.SCREENSHOT, "a"), b"1")
        await store.save(cycle_id, _make_artifact(ArtifactType.VIDEO, "b"), b"2")
        result = await store.list_by_cycle(cycle_id)
        assert len(result) == 2
        types = {a.type for a in result}
        assert types == {ArtifactType.SCREENSHOT, ArtifactType.VIDEO}

    async def test_list_ignores_other_cycles(self, store):
        c1 = CycleId("cycle-1")
        c2 = CycleId("cycle-2")
        await store.save(c1, _make_artifact(label="x"), b"1")
        await store.save(c2, _make_artifact(label="y"), b"2")
        result = await store.list_by_cycle(c1)
        assert len(result) == 1

    async def test_list_skips_unknown_type_dirs(self, store, cycle_id, tmp_path):
        # Create an unknown type directory
        bad_dir = tmp_path / "artifacts" / str(cycle_id) / "unknown_type"
        bad_dir.mkdir(parents=True)
        (bad_dir / "file.txt").write_bytes(b"junk")
        result = await store.list_by_cycle(cycle_id)
        assert result == []


class TestBaseDir:
    def test_custom_base_dir(self, tmp_path):
        store = LocalArtifactStore(base_dir=str(tmp_path / "custom"))
        assert store.base_dir == str(tmp_path / "custom")

    def test_default_base_dir(self):
        store = LocalArtifactStore()
        assert ".swarm-data/artifacts" in store.base_dir
