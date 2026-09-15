"""Tests for the artifacts route."""

from __future__ import annotations

import os

import pytest
from httpx import ASGITransport, AsyncClient

from theswarm.presentation.web.routes.artifacts import router


@pytest.fixture
def artifact_dir(tmp_path):
    """Create a fake artifact directory with a test screenshot."""
    art_dir = tmp_path / "artifacts"
    cycle_dir = art_dir / "cycle-001" / "screenshot"
    cycle_dir.mkdir(parents=True)
    (cycle_dir / "homepage.png").write_bytes(b"\x89PNG_TEST")
    return art_dir


@pytest.fixture
async def client(artifact_dir):
    """Create a test client with the artifacts router."""
    from fastapi import FastAPI
    from unittest.mock import MagicMock

    app = FastAPI()
    store = MagicMock()
    store.base_dir = str(artifact_dir)
    app.state.artifact_store = store
    app.include_router(router)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestServeArtifact:
    async def test_serves_existing_file(self, client):
        resp = await client.get("/artifacts/cycle-001/screenshot/homepage.png")
        assert resp.status_code == 200
        assert resp.content == b"\x89PNG_TEST"
        assert resp.headers["content-type"] == "image/png"

    async def test_returns_404_for_missing(self, client):
        resp = await client.get("/artifacts/cycle-001/screenshot/missing.png")
        assert resp.status_code == 404

    async def test_blocks_path_traversal(self, client):
        resp = await client.get("/artifacts/../../../etc/passwd")
        assert resp.status_code in (403, 404)


class TestListArtifacts:
    async def test_lists_artifacts_for_cycle(self, client):
        resp = await client.get("/artifacts/list?cycle_id=cycle-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["artifacts"][0]["name"] == "homepage.png"

    async def test_returns_empty_for_unknown_cycle(self, client):
        resp = await client.get("/artifacts/list?cycle_id=unknown")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


class TestMediaTypes:
    """The recorder writes JPEG thumbnails and GIF previews next to the
    webm. Served as octet-stream they rendered in <img> only by browser
    sniffing, and not as a <video> poster everywhere."""

    @pytest.mark.parametrize("name, media_type", [
        ("thumb.jpg", "image/jpeg"),
        ("thumb.jpeg", "image/jpeg"),
        ("preview.gif", "image/gif"),
        ("clip.mp4", "video/mp4"),
        ("clip.webm", "video/webm"),
    ])
    async def test_served_with_its_real_media_type(self, client, artifact_dir, name, media_type):
        (artifact_dir / "cycle-001" / "video").mkdir(parents=True, exist_ok=True)
        (artifact_dir / "cycle-001" / "video" / name).write_bytes(b"x")

        resp = await client.get(f"/artifacts/cycle-001/video/{name}")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == media_type

    async def test_unknown_extensions_stay_opaque(self, client, artifact_dir):
        (artifact_dir / "cycle-001" / "misc").mkdir(parents=True, exist_ok=True)
        (artifact_dir / "cycle-001" / "misc" / "blob.bin").write_bytes(b"x")

        resp = await client.get("/artifacts/cycle-001/misc/blob.bin")

        assert resp.headers["content-type"] == "application/octet-stream"
