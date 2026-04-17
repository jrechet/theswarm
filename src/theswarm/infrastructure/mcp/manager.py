"""MCP skill lifecycle manager — mount/unmount skills per task."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .manifest import SkillDependency, SkillManifest

log = logging.getLogger(__name__)


@dataclass
class MountedSkill:
    name: str
    category: str
    active: bool = True


class SkillMCPManager:
    """Manages mounting/unmounting of skill-embedded MCPs."""

    def __init__(self, manifest: SkillManifest | None = None):
        self._manifest = manifest or SkillManifest()
        self._mounted: dict[str, MountedSkill] = {}
        # Auto-mount always-on skills
        for entry in self._manifest.get_always_on():
            for skill in entry.skills:
                self._mounted[skill.name] = MountedSkill(
                    name=skill.name, category=entry.category
                )

    async def mount_for_task(self, category: str) -> list[str]:
        """Mount all skills required for a task category.

        Returns list of newly mounted skill names.
        """
        skills = self._manifest.get_skills_for_category(category)
        newly_mounted: list[str] = []
        for skill in skills:
            if skill.name in self._mounted:
                log.debug("Skill %s already mounted, skipping", skill.name)
                continue
            self._mounted[skill.name] = MountedSkill(
                name=skill.name, category=category
            )
            newly_mounted.append(skill.name)
            log.info("Mounted skill %s for category %s", skill.name, category)
        return newly_mounted

    async def unmount_for_task(self, category: str) -> list[str]:
        """Unmount skills that were mounted for a task category (unless always-on).

        Returns unmounted names.
        """
        always_on_names = {
            skill.name
            for entry in self._manifest.get_always_on()
            for skill in entry.skills
        }
        unmounted: list[str] = []
        to_remove = [
            name
            for name, mounted in self._mounted.items()
            if mounted.category == category and name not in always_on_names
        ]
        for name in to_remove:
            del self._mounted[name]
            unmounted.append(name)
            log.info("Unmounted skill %s from category %s", name, category)
        return unmounted

    def get_mounted(self) -> list[MountedSkill]:
        """List currently mounted skills."""
        return list(self._mounted.values())

    def get_status(self) -> dict:
        """Return status for API/dashboard."""
        return {
            "mounted": [
                {"name": s.name, "category": s.category, "active": s.active}
                for s in self._mounted.values()
            ],
            "categories": self._manifest.list_categories(),
            "manifest": self._manifest.to_dict(),
        }
