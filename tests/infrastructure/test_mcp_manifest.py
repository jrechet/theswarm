"""Tests for Skill-Embedded MCP manifest and manager."""

from __future__ import annotations

import json

import pytest

from theswarm.infrastructure.mcp.manager import MountedSkill, SkillMCPManager
from theswarm.infrastructure.mcp.manifest import (
    SkillDependency,
    SkillManifest,
    SkillManifestEntry,
)


# ── Fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def custom_manifest() -> dict[str, SkillManifestEntry]:
    return {
        "memory": SkillManifestEntry(
            category="memory",
            description="Agent memory",
            skills=[SkillDependency("memory_store")],
            always_on=True,
        ),
        "testing": SkillManifestEntry(
            category="testing",
            description="Test runner",
            skills=[SkillDependency("pytest_runner")],
        ),
        "browser": SkillManifestEntry(
            category="browser",
            description="Browser automation",
            skills=[
                SkillDependency("playwright", required=False),
                SkillDependency("screenshots"),
            ],
        ),
    }


@pytest.fixture
def manifest(custom_manifest) -> SkillManifest:
    return SkillManifest(custom_manifest)


@pytest.fixture
def manager(manifest) -> SkillMCPManager:
    return SkillMCPManager(manifest)


# ── SkillManifest ────────────────────────────────────────────────────


class TestSkillManifest:
    def test_get_skills_for_known_category(self, manifest):
        skills = manifest.get_skills_for_category("testing")
        assert len(skills) == 1
        assert skills[0].name == "pytest_runner"
        assert skills[0].required is True

    def test_get_skills_for_unknown_category(self, manifest):
        assert manifest.get_skills_for_category("nonexistent") == []

    def test_get_skills_multiple(self, manifest):
        skills = manifest.get_skills_for_category("browser")
        assert len(skills) == 2
        names = {s.name for s in skills}
        assert names == {"playwright", "screenshots"}

    def test_get_always_on(self, manifest):
        always = manifest.get_always_on()
        assert len(always) == 1
        assert always[0].category == "memory"

    def test_list_categories(self, manifest):
        cats = manifest.list_categories()
        assert set(cats) == {"memory", "testing", "browser"}

    def test_to_dict(self, manifest):
        d = manifest.to_dict()
        assert "memory" in d
        assert d["memory"]["always_on"] is True
        assert d["testing"]["description"] == "Test runner"

    def test_from_json(self, tmp_path):
        data = {
            "ci": {
                "category": "ci",
                "description": "CI pipeline",
                "skills": [{"name": "github_actions", "required": True}],
                "always_on": False,
            },
        }
        path = tmp_path / "manifest.json"
        path.write_text(json.dumps(data))

        loaded = SkillManifest.from_json(path)
        skills = loaded.get_skills_for_category("ci")
        assert len(skills) == 1
        assert skills[0].name == "github_actions"
        assert loaded.get_always_on() == []


# ── SkillMCPManager ─────────────────────────────────────────────────


class TestSkillMCPManager:
    def test_auto_mounts_always_on(self, manager):
        mounted = manager.get_mounted()
        names = {s.name for s in mounted}
        assert "memory_store" in names

    async def test_mount_for_task(self, manager):
        newly = await manager.mount_for_task("testing")
        assert newly == ["pytest_runner"]
        names = {s.name for s in manager.get_mounted()}
        assert "pytest_runner" in names
        assert "memory_store" in names

    async def test_mount_idempotent(self, manager):
        await manager.mount_for_task("testing")
        second = await manager.mount_for_task("testing")
        assert second == []

    async def test_unmount_for_task(self, manager):
        await manager.mount_for_task("browser")
        unmounted = await manager.unmount_for_task("browser")
        assert set(unmounted) == {"playwright", "screenshots"}
        names = {s.name for s in manager.get_mounted()}
        assert "playwright" not in names
        assert "screenshots" not in names

    async def test_unmount_preserves_always_on(self, manager):
        unmounted = await manager.unmount_for_task("memory")
        assert unmounted == []
        names = {s.name for s in manager.get_mounted()}
        assert "memory_store" in names

    async def test_unmount_unknown_category(self, manager):
        unmounted = await manager.unmount_for_task("nonexistent")
        assert unmounted == []

    def test_get_status(self, manager):
        status = manager.get_status()
        assert "mounted" in status
        assert "categories" in status
        assert "manifest" in status
        assert isinstance(status["mounted"], list)
        assert isinstance(status["categories"], list)
        assert isinstance(status["manifest"], dict)
        # Always-on skill present in mounted
        mounted_names = {s["name"] for s in status["mounted"]}
        assert "memory_store" in mounted_names

    async def test_full_lifecycle(self, manager):
        # Start: only always-on
        assert len(manager.get_mounted()) == 1

        # Mount testing
        await manager.mount_for_task("testing")
        assert len(manager.get_mounted()) == 2

        # Mount browser
        await manager.mount_for_task("browser")
        assert len(manager.get_mounted()) == 4

        # Unmount testing
        unmounted = await manager.unmount_for_task("testing")
        assert unmounted == ["pytest_runner"]
        assert len(manager.get_mounted()) == 3

        # Unmount browser
        unmounted = await manager.unmount_for_task("browser")
        assert set(unmounted) == {"playwright", "screenshots"}
        assert len(manager.get_mounted()) == 1

        # Only always-on remains
        assert manager.get_mounted()[0].name == "memory_store"
