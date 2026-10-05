"""The CLI reads `.env` like the server does.

The README's Quickstart writes .env and runs `python -m theswarm validate`;
on 2026-10-05 that warned "GITHUB_TOKEN not set" and "the auth wall is up
but nobody can log in" with both set in the file — only the server's config
loader called `load_dotenv()`.
"""

from __future__ import annotations

import os

from theswarm.presentation.cli import main as cli


def test_the_cli_loads_dotenv_before_the_command(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("SWARM_GITHUB_REPO=o/from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SWARM_SKIP_DOTENV", raising=False)
    monkeypatch.delenv("SWARM_GITHUB_REPO", raising=False)
    seen: list[str | None] = []

    async def fake_status(args):
        seen.append(os.environ.get("SWARM_GITHUB_REPO"))

    monkeypatch.setattr(cli, "cmd_status", fake_status)
    cli.main(["status"])

    assert seen == ["o/from-dotenv"]


def test_the_real_environment_wins_over_dotenv(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("SWARM_GITHUB_REPO=o/from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SWARM_SKIP_DOTENV", raising=False)
    monkeypatch.setenv("SWARM_GITHUB_REPO", "o/from-env")

    cli.load_env()

    assert os.environ["SWARM_GITHUB_REPO"] == "o/from-env"


def test_the_suite_s_switch_keeps_the_laptop_s_dotenv_out(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("SWARM_GITHUB_REPO=o/from-dotenv\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SWARM_SKIP_DOTENV", "1")
    monkeypatch.delenv("SWARM_GITHUB_REPO", raising=False)

    cli.load_env()

    assert "SWARM_GITHUB_REPO" not in os.environ
