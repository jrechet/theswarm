"""Local filesystem artifact storage for screenshots and videos."""

from __future__ import annotations

import os
from pathlib import Path

from theswarm.domain.cycles.value_objects import CycleId
from theswarm.domain.reporting.value_objects import Artifact, ArtifactType


class LocalArtifactStore:
    """Stores artifacts (screenshots, videos, logs) on the local filesystem.

    Implements the ArtifactStore protocol from domain/reporting/ports.py.

    Layout:
        {base_dir}/{cycle_id}/{artifact_type}/{filename}
    """

    def __init__(self, base_dir: str = "") -> None:
        if not base_dir:
            base_dir = os.path.join(os.path.expanduser("~"), ".swarm-data", "artifacts")
        self._base_dir = Path(base_dir)

    @property
    def base_dir(self) -> str:
        return str(self._base_dir)

    async def save(self, cycle_id: CycleId, artifact: Artifact, data: bytes) -> str:
        """Save artifact data to disk. Returns the relative file path."""
        type_dir = artifact.type.value
        dir_path = self._base_dir / str(cycle_id) / type_dir
        dir_path.mkdir(parents=True, exist_ok=True)

        filename = artifact.label.replace("/", "_").replace(" ", "_")
        if not filename:
            filename = "artifact"

        ext = _extension_for_type(artifact.type, artifact.mime_type)
        filepath = dir_path / f"{filename}{ext}"

        # Avoid overwriting
        counter = 1
        while filepath.exists():
            filepath = dir_path / f"{filename}_{counter}{ext}"
            counter += 1

        filepath.write_bytes(data)
        return str(filepath.relative_to(self._base_dir))

    async def get_url(self, path: str) -> str:
        """Return a URL to access an artifact. For local store, returns file path."""
        full = self._base_dir / path
        if full.exists():
            return str(full)
        return f"/artifacts/{path}"

    async def list_by_cycle(self, cycle_id: CycleId) -> list[Artifact]:
        """List all artifacts for a cycle."""
        cycle_dir = self._base_dir / str(cycle_id)
        if not cycle_dir.is_dir():
            return []

        artifacts: list[Artifact] = []
        for type_dir in cycle_dir.iterdir():
            if not type_dir.is_dir():
                continue
            art_type = _type_from_dirname(type_dir.name)
            if art_type is None:
                continue
            for f in sorted(type_dir.iterdir()):
                if f.is_file():
                    artifacts.append(
                        Artifact(
                            type=art_type,
                            path=str(f.relative_to(self._base_dir)),
                            label=f.stem,
                            size_bytes=f.stat().st_size,
                        )
                    )
        return artifacts


def _extension_for_type(art_type: ArtifactType, mime_type: str = "") -> str:
    # Honour an explicit mime on the artifact so we can distinguish e.g.
    # a JPEG thumbnail or GIF preview from the default PNG/webm.
    mime_overrides = {
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/png": ".png",
        "video/mp4": ".mp4",
        "video/webm": ".webm",
    }
    if mime_type and mime_type in mime_overrides:
        return mime_overrides[mime_type]
    return {
        ArtifactType.SCREENSHOT: ".png",
        ArtifactType.VIDEO: ".webm",
        ArtifactType.DIFF: ".diff",
        ArtifactType.LOG: ".log",
    }.get(art_type, ".bin")


def _type_from_dirname(name: str) -> ArtifactType | None:
    try:
        return ArtifactType(name)
    except ValueError:
        return None
