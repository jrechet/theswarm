"""Tests for infrastructure/vcs/framework_detector.py."""

from __future__ import annotations

import os

import pytest

from theswarm.domain.projects.value_objects import Framework
from theswarm.infrastructure.vcs.framework_detector import FileSystemFrameworkDetector


@pytest.fixture()
def detector():
    return FileSystemFrameworkDetector()


class TestFrameworkDetector:
    async def test_nonexistent_dir(self, detector):
        info = await detector.detect("/nonexistent/path")
        assert info.framework == Framework.GENERIC
        assert info.test_command == ""

    async def test_fastapi_detection(self, detector, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]\n')
        (tmp_path / "src").mkdir()

        info = await detector.detect(str(tmp_path))
        assert info.framework == Framework.FASTAPI
        assert info.test_command == "pytest tests/"
        assert info.source_dir == "src/"

    async def test_django_detection(self, detector, tmp_path):
        (tmp_path / "manage.py").write_text("#!/usr/bin/env python\n")
        (tmp_path / "requirements.txt").write_text("django==4.2\n")

        info = await detector.detect(str(tmp_path))
        assert info.framework == Framework.DJANGO
        assert info.test_command == "python manage.py test"

    async def test_flask_detection(self, detector, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask==3.0\n")

        info = await detector.detect(str(tmp_path))
        assert info.framework == Framework.FLASK
        assert info.test_command == "pytest tests/"

    async def test_nextjs_detection(self, detector, tmp_path):
        (tmp_path / "package.json").write_text('{"dependencies": {"next": "14.0.0"}}')
        (tmp_path / "next.config.js").write_text("module.exports = {}")

        info = await detector.detect(str(tmp_path))
        assert info.framework == Framework.NEXTJS
        assert info.test_command == "npm test"

    async def test_nextjs_mjs(self, detector, tmp_path):
        (tmp_path / "next.config.mjs").write_text("export default {}")
        (tmp_path / "package.json").write_text("{}")

        info = await detector.detect(str(tmp_path))
        assert info.framework == Framework.NEXTJS

    async def test_nextjs_ts(self, detector, tmp_path):
        (tmp_path / "next.config.ts").write_text("export default {}")
        (tmp_path / "package.json").write_text("{}")

        info = await detector.detect(str(tmp_path))
        assert info.framework == Framework.NEXTJS

    async def test_express_detection(self, detector, tmp_path):
        (tmp_path / "package.json").write_text('{"dependencies": {"express": "4.18.0"}}')

        info = await detector.detect(str(tmp_path))
        assert info.framework == Framework.EXPRESS
        assert info.test_command == "npm test"

    async def test_generic_python(self, detector, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "mylib"\n')

        info = await detector.detect(str(tmp_path))
        assert info.framework == Framework.GENERIC
        assert info.test_command == "pytest tests/"

    async def test_generic_node(self, detector, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "mylib"}')

        info = await detector.detect(str(tmp_path))
        assert info.framework == Framework.GENERIC
        assert info.test_command == "npm test"

    async def test_generic_rust(self, detector, tmp_path):
        (tmp_path / "Cargo.toml").write_text('[package]\nname = "mylib"\n')

        info = await detector.detect(str(tmp_path))
        assert info.framework == Framework.GENERIC
        assert info.test_command == "cargo test"

    async def test_generic_go(self, detector, tmp_path):
        (tmp_path / "go.mod").write_text("module github.com/o/r\n")

        info = await detector.detect(str(tmp_path))
        assert info.framework == Framework.GENERIC
        assert info.test_command == "go test ./..."

    async def test_empty_dir(self, detector, tmp_path):
        info = await detector.detect(str(tmp_path))
        assert info.framework == Framework.GENERIC
        assert info.test_command == ""

    async def test_source_dir_detection(self, detector, tmp_path):
        (tmp_path / "app").mkdir()
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')

        info = await detector.detect(str(tmp_path))
        assert info.source_dir == "app/"

    async def test_lib_dir_detection(self, detector, tmp_path):
        (tmp_path / "lib").mkdir()
        (tmp_path / "package.json").write_text("{}")

        info = await detector.detect(str(tmp_path))
        assert info.source_dir == "lib/"

    async def test_default_branch_from_git(self, detector, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/develop\n")
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')

        info = await detector.detect(str(tmp_path))
        assert info.default_branch == "develop"

    async def test_default_branch_no_git(self, detector, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')

        info = await detector.detect(str(tmp_path))
        assert info.default_branch == "main"

    async def test_fastapi_from_requirements_txt(self, detector, tmp_path):
        (tmp_path / "requirements.txt").write_text("fastapi>=0.100\nuvicorn\n")

        info = await detector.detect(str(tmp_path))
        assert info.framework == Framework.FASTAPI

    async def test_fastapi_priority_over_django_when_both(self, detector, tmp_path):
        """FastAPI check runs before manage.py check."""
        (tmp_path / "pyproject.toml").write_text('dependencies = ["fastapi"]\n')

        info = await detector.detect(str(tmp_path))
        assert info.framework == Framework.FASTAPI
