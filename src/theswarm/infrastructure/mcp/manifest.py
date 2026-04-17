"""Skill manifest — maps task categories to required MCP servers/skills."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class SkillDependency:
    name: str
    required: bool = True


@dataclass
class SkillManifestEntry:
    category: str
    description: str
    skills: list[SkillDependency] = field(default_factory=list)
    always_on: bool = False


# Default manifest — which skills each task category needs
DEFAULT_MANIFEST: dict[str, SkillManifestEntry] = {
    "memory": SkillManifestEntry(
        category="memory",
        description="Agent memory read/write",
        skills=[SkillDependency("memory_store")],
        always_on=True,
    ),
    "code_search": SkillManifestEntry(
        category="code_search",
        description="Code search and navigation",
        skills=[SkillDependency("ast_grep", required=False)],
    ),
    "testing": SkillManifestEntry(
        category="testing",
        description="Test execution and coverage",
        skills=[SkillDependency("pytest_runner")],
    ),
    "browser": SkillManifestEntry(
        category="browser",
        description="Browser automation for E2E tests",
        skills=[SkillDependency("playwright", required=False)],
    ),
}


class SkillManifest:
    """Manages which skills are needed for each task category."""

    def __init__(self, manifest: dict[str, SkillManifestEntry] | None = None):
        self._manifest = manifest or dict(DEFAULT_MANIFEST)

    def get_skills_for_category(self, category: str) -> list[SkillDependency]:
        """Get required skills for a task category."""
        entry = self._manifest.get(category)
        if not entry:
            return []
        return entry.skills

    def get_always_on(self) -> list[SkillManifestEntry]:
        """Get skills that should always be loaded."""
        return [e for e in self._manifest.values() if e.always_on]

    def list_categories(self) -> list[str]:
        """List all known task categories."""
        return list(self._manifest.keys())

    @classmethod
    def from_json(cls, path: str | Path) -> SkillManifest:
        """Load manifest from a JSON file."""
        raw = json.loads(Path(path).read_text())
        manifest: dict[str, SkillManifestEntry] = {}
        for key, val in raw.items():
            skills = [SkillDependency(**s) for s in val.get("skills", [])]
            manifest[key] = SkillManifestEntry(
                category=val["category"],
                description=val["description"],
                skills=skills,
                always_on=val.get("always_on", False),
            )
        return cls(manifest)

    def to_dict(self) -> dict:
        """Serialize for API/dashboard."""
        return {key: asdict(entry) for key, entry in self._manifest.items()}
