"""QA starts a target the way the target declares — in a scrubbed environment.

The QA phase assumed every target was a FastAPI app at `src.main:app`.
TheSwarm's own repository is `python -m theswarm serve`, so the swarm
could not demo itself: no screenshots, no video, and an E2E report of
"145 total, 0 passed, 13 failed, 132 unaccounted for" (#110). And a
second instance of the swarm must never inherit the first one's tokens.
"""

from __future__ import annotations

import os

from theswarm.agents.qa import _demo_launch, _demo_spec

PY = "/usr/local/bin/python3"

THESWARM_YAML = """
server:
  port: 8091

demo:
  command: "{python} -m theswarm serve --host 127.0.0.1 --port {port} --db {tmp}/demo.db"
  env:
    SWARM_AUTH_DISABLED: "1"
    BASE_PATH: ""
"""


class TestTheDefault:
    def test_no_manifest_means_uvicorn_on_src_main(self, tmp_path):
        command, env = _demo_launch(str(tmp_path), PY, 8001)

        assert command == [PY, "-m", "uvicorn", "src.main:app", "--host", "127.0.0.1", "--port", "8001"]

    def test_the_default_keeps_the_environment_it_always_had(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "sqlite:///demo.db")

        _, env = _demo_launch(str(tmp_path), PY, 8001)

        assert env["DATABASE_URL"] == "sqlite:///demo.db"

    def test_a_manifest_without_a_demo_section_is_the_default(self, tmp_path):
        (tmp_path / "theswarm.yaml").write_text("server:\n  port: 8091\n")

        command, _ = _demo_launch(str(tmp_path), PY, 8001)

        assert "uvicorn" in command


class TestADeclaredDemo:
    def test_placeholders_are_filled_in(self, tmp_path):
        (tmp_path / "theswarm.yaml").write_text(THESWARM_YAML)

        command, _ = _demo_launch(str(tmp_path), PY, 8002)

        assert command[:5] == [PY, "-m", "theswarm", "serve", "--host"]
        assert "8002" in command
        db = command[command.index("--db") + 1]
        assert db.endswith("/demo.db")
        assert os.path.isdir(os.path.dirname(db))  # {tmp} is a real, fresh directory

    def test_declared_env_reaches_the_process(self, tmp_path):
        (tmp_path / "theswarm.yaml").write_text(THESWARM_YAML)

        _, env = _demo_launch(str(tmp_path), PY, 8002)

        assert env["SWARM_AUTH_DISABLED"] == "1"
        assert env["BASE_PATH"] == ""

    def test_the_swarms_own_secrets_do_not(self, tmp_path, monkeypatch):
        """The whole point: a second instance holding the real tokens would
        connect a second bot and read the real installation."""
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_real")
        monkeypatch.setenv("MATTERMOST_BOT_TOKEN", "mm_real")
        monkeypatch.setenv("SWARM_PO_MATTERMOST_TOKEN", "mm_real_2")
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat-real")
        monkeypatch.setenv("SEQ_API_KEY", "seq_real")
        (tmp_path / "theswarm.yaml").write_text(THESWARM_YAML)

        _, env = _demo_launch(str(tmp_path), PY, 8002)

        for secret in ("GITHUB_TOKEN", "MATTERMOST_BOT_TOKEN", "SWARM_PO_MATTERMOST_TOKEN",
                       "CLAUDE_CODE_OAUTH_TOKEN", "SEQ_API_KEY"):
            assert secret not in env

    def test_path_and_home_survive_the_scrub(self, tmp_path):
        (tmp_path / "theswarm.yaml").write_text(THESWARM_YAML)

        _, env = _demo_launch(str(tmp_path), PY, 8002)

        assert env["PATH"] == os.environ["PATH"]
        assert "HOME" in env

    def test_a_broken_manifest_falls_back_to_the_default(self, tmp_path):
        (tmp_path / "theswarm.yaml").write_text("demo: [unbalanced")

        command, _ = _demo_launch(str(tmp_path), PY, 8001)

        assert "uvicorn" in command

    def test_the_spec_reader_alone(self, tmp_path):
        (tmp_path / "theswarm.yaml").write_text(THESWARM_YAML)

        spec = _demo_spec(str(tmp_path))

        assert "theswarm serve" in spec["command"]
        assert spec["env"]["SWARM_AUTH_DISABLED"] == "1"


class TestTheRepositoryDeclaresItself:
    def test_theswarm_yaml_at_the_repo_root_declares_a_demo(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        spec = _demo_spec(root)

        assert "theswarm serve" in spec["command"]
        assert spec["env"]["SWARM_AUTH_DISABLED"] == "1"
