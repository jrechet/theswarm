"""Auto-detect project framework from workspace files."""

from __future__ import annotations

import os

from theswarm.domain.projects.value_objects import Framework, FrameworkInfo


# Detection rules: (filename_or_pattern, framework, test_cmd, source_dir, entry_point)
_DETECTION_RULES: list[tuple[str, Framework, str, str, str]] = [
    ("pyproject.toml", Framework.GENERIC, "pytest tests/", "src/", ""),
    ("requirements.txt", Framework.GENERIC, "pytest tests/", ".", ""),
    ("manage.py", Framework.DJANGO, "python manage.py test", ".", "manage.py"),
    ("package.json", Framework.GENERIC, "npm test", "src/", ""),
    ("next.config.js", Framework.NEXTJS, "npm test", "src/", ""),
    ("next.config.mjs", Framework.NEXTJS, "npm test", "src/", ""),
    ("next.config.ts", Framework.NEXTJS, "npm test", "src/", ""),
    ("Cargo.toml", Framework.GENERIC, "cargo test", "src/", ""),
    ("go.mod", Framework.GENERIC, "go test ./...", ".", ""),
]


async def _check_fastapi(workspace: str) -> bool:
    """Check if workspace uses FastAPI by scanning pyproject.toml or requirements."""
    for fname in ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg"):
        fpath = os.path.join(workspace, fname)
        if os.path.isfile(fpath):
            try:
                with open(fpath, encoding="utf-8") as f:
                    content = f.read().lower()
                if "fastapi" in content:
                    return True
            except OSError:
                continue
    return False


async def _check_flask(workspace: str) -> bool:
    """Check if workspace uses Flask."""
    for fname in ("pyproject.toml", "requirements.txt", "setup.py", "setup.cfg"):
        fpath = os.path.join(workspace, fname)
        if os.path.isfile(fpath):
            try:
                with open(fpath, encoding="utf-8") as f:
                    content = f.read().lower()
                if "flask" in content:
                    return True
            except OSError:
                continue
    return False


async def _check_express(workspace: str) -> bool:
    """Check if workspace uses Express."""
    pkg = os.path.join(workspace, "package.json")
    if os.path.isfile(pkg):
        try:
            with open(pkg, encoding="utf-8") as f:
                content = f.read().lower()
            return '"express"' in content
        except OSError:
            pass
    return False


async def _detect_default_branch(workspace: str) -> str:
    """Check .git/HEAD for default branch name."""
    head = os.path.join(workspace, ".git", "HEAD")
    if os.path.isfile(head):
        try:
            with open(head, encoding="utf-8") as f:
                content = f.read().strip()
            if content.startswith("ref: refs/heads/"):
                return content.split("/")[-1]
        except OSError:
            pass
    return "main"


async def _detect_source_dir(workspace: str) -> str:
    """Check common source directories."""
    for candidate in ("src/", "app/", "lib/"):
        if os.path.isdir(os.path.join(workspace, candidate)):
            return candidate
    return "."


class FileSystemFrameworkDetector:
    """Detects framework by scanning workspace files.

    Implements the FrameworkDetector protocol from domain/projects/ports.py.
    """

    async def detect(self, workspace_path: str) -> FrameworkInfo:
        if not os.path.isdir(workspace_path):
            return FrameworkInfo(
                framework=Framework.GENERIC,
                test_command="",
                source_dir=".",
                entry_point="",
                default_branch="main",
            )

        default_branch = await _detect_default_branch(workspace_path)
        source_dir = await _detect_source_dir(workspace_path)

        # Check specific frameworks first (more specific beats generic)
        if await _check_fastapi(workspace_path):
            return FrameworkInfo(
                framework=Framework.FASTAPI,
                test_command="pytest tests/",
                source_dir=source_dir,
                entry_point="src.main:app",
                default_branch=default_branch,
            )

        if os.path.isfile(os.path.join(workspace_path, "manage.py")):
            return FrameworkInfo(
                framework=Framework.DJANGO,
                test_command="python manage.py test",
                source_dir=source_dir,
                entry_point="manage.py",
                default_branch=default_branch,
            )

        if await _check_flask(workspace_path):
            return FrameworkInfo(
                framework=Framework.FLASK,
                test_command="pytest tests/",
                source_dir=source_dir,
                entry_point="app:create_app",
                default_branch=default_branch,
            )

        for pattern in ("next.config.js", "next.config.mjs", "next.config.ts"):
            if os.path.isfile(os.path.join(workspace_path, pattern)):
                return FrameworkInfo(
                    framework=Framework.NEXTJS,
                    test_command="npm test",
                    source_dir=source_dir,
                    entry_point="",
                    default_branch=default_branch,
                )

        if await _check_express(workspace_path):
            return FrameworkInfo(
                framework=Framework.EXPRESS,
                test_command="npm test",
                source_dir=source_dir,
                entry_point="index.js",
                default_branch=default_branch,
            )

        # Fall back to generic detection
        test_command = ""
        if os.path.isfile(os.path.join(workspace_path, "pyproject.toml")):
            test_command = "pytest tests/"
        elif os.path.isfile(os.path.join(workspace_path, "package.json")):
            test_command = "npm test"
        elif os.path.isfile(os.path.join(workspace_path, "Cargo.toml")):
            test_command = "cargo test"
        elif os.path.isfile(os.path.join(workspace_path, "go.mod")):
            test_command = "go test ./..."

        return FrameworkInfo(
            framework=Framework.GENERIC,
            test_command=test_command,
            source_dir=source_dir,
            entry_point="",
            default_branch=default_branch,
        )
