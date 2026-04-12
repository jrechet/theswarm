"""Tests for presentation/cli/main.py."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, patch

import pytest

from theswarm.presentation.cli.main import create_parser, main


class TestParser:
    def test_no_args(self):
        parser = create_parser()
        args = parser.parse_args([])
        assert args.command is None

    def test_serve(self):
        parser = create_parser()
        args = parser.parse_args(["serve"])
        assert args.command == "serve"
        assert args.host == "0.0.0.0"
        assert args.port == 8091

    def test_serve_custom_port(self):
        parser = create_parser()
        args = parser.parse_args(["serve", "--port", "9000"])
        assert args.port == 9000

    def test_dashboard(self):
        parser = create_parser()
        args = parser.parse_args(["dashboard"])
        assert args.command == "dashboard"

    def test_cycle(self):
        parser = create_parser()
        args = parser.parse_args(["cycle", "--project", "my-app"])
        assert args.command == "cycle"
        assert args.project == "my-app"
        assert args.triggered_by == "cli"

    def test_cycle_requires_project(self):
        parser = create_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["cycle"])

    def test_projects_list(self):
        parser = create_parser()
        args = parser.parse_args(["projects", "list"])
        assert args.command == "projects"
        assert args.projects_command == "list"

    def test_projects_add(self):
        parser = create_parser()
        args = parser.parse_args(["projects", "add", "my-app", "owner/my-app"])
        assert args.projects_command == "add"
        assert args.project_id == "my-app"
        assert args.repo == "owner/my-app"
        assert args.framework == "auto"

    def test_projects_add_with_framework(self):
        parser = create_parser()
        args = parser.parse_args([
            "projects", "add", "x", "o/x", "--framework", "fastapi",
        ])
        assert args.framework == "fastapi"

    def test_projects_remove(self):
        parser = create_parser()
        args = parser.parse_args(["projects", "remove", "my-app"])
        assert args.projects_command == "remove"
        assert args.project_id == "my-app"

    def test_status(self):
        parser = create_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"


class TestMain:
    def test_no_command_exits_0(self):
        with pytest.raises(SystemExit) as exc_info:
            main([])
        assert exc_info.value.code == 0

    def test_projects_list_empty(self, tmp_path):
        """Integration test: projects list with empty DB."""
        db_path = str(tmp_path / "test.db")

        with patch("theswarm.presentation.cli.main._init_db") as mock_init:
            import aiosqlite

            async def fake_init(path=""):
                from theswarm.infrastructure.persistence.sqlite_repos import init_db
                return await init_db(db_path)

            mock_init.side_effect = fake_init
            main(["projects", "list"])

    def test_projects_add_and_list(self, tmp_path, capsys):
        db_path = str(tmp_path / "test.db")

        with patch("theswarm.presentation.cli.main._init_db") as mock_init:
            async def fake_init(path=""):
                from theswarm.infrastructure.persistence.sqlite_repos import init_db
                return await init_db(db_path)

            mock_init.side_effect = fake_init

            main(["projects", "add", "my-app", "owner/my-app"])
            captured = capsys.readouterr()
            assert "Added project: my-app" in captured.out

            main(["projects", "list"])
            captured = capsys.readouterr()
            assert "my-app" in captured.out

    def test_projects_add_duplicate(self, tmp_path):
        db_path = str(tmp_path / "test.db")

        with patch("theswarm.presentation.cli.main._init_db") as mock_init:
            async def fake_init(path=""):
                from theswarm.infrastructure.persistence.sqlite_repos import init_db
                return await init_db(db_path)

            mock_init.side_effect = fake_init

            main(["projects", "add", "x", "o/x"])
            with pytest.raises(SystemExit) as exc_info:
                main(["projects", "add", "x", "o/x"])
            assert exc_info.value.code == 1

    def test_projects_remove(self, tmp_path, capsys):
        db_path = str(tmp_path / "test.db")

        with patch("theswarm.presentation.cli.main._init_db") as mock_init:
            async def fake_init(path=""):
                from theswarm.infrastructure.persistence.sqlite_repos import init_db
                return await init_db(db_path)

            mock_init.side_effect = fake_init

            main(["projects", "add", "rm-me", "o/rm-me"])
            main(["projects", "remove", "rm-me"])
            captured = capsys.readouterr()
            assert "Removed" in captured.out

    def test_status(self, tmp_path, capsys):
        db_path = str(tmp_path / "test.db")

        with patch("theswarm.presentation.cli.main._init_db") as mock_init:
            async def fake_init(path=""):
                from theswarm.infrastructure.persistence.sqlite_repos import init_db
                return await init_db(db_path)

            mock_init.side_effect = fake_init

            main(["status"])
            captured = capsys.readouterr()
            assert "Projects:" in captured.out
            assert "Active cycles:" in captured.out

    def test_cycle_unknown_project(self, tmp_path):
        db_path = str(tmp_path / "test.db")

        with patch("theswarm.presentation.cli.main._init_db") as mock_init:
            async def fake_init(path=""):
                from theswarm.infrastructure.persistence.sqlite_repos import init_db
                return await init_db(db_path)

            mock_init.side_effect = fake_init

            with pytest.raises(SystemExit) as exc_info:
                main(["cycle", "--project", "nope"])
            assert exc_info.value.code == 1

    def test_cycle_success(self, tmp_path, capsys):
        db_path = str(tmp_path / "test.db")

        with patch("theswarm.presentation.cli.main._init_db") as mock_init:
            async def fake_init(path=""):
                from theswarm.infrastructure.persistence.sqlite_repos import init_db
                return await init_db(db_path)

            mock_init.side_effect = fake_init

            # First add a project
            main(["projects", "add", "p1", "o/p1"])
            # Then run cycle
            main(["cycle", "--project", "p1"])
            captured = capsys.readouterr()
            assert "Cycle started:" in captured.out
