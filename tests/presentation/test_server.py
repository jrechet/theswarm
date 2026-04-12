"""Tests for presentation/web/server.py — the unified server module."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── GatewayBridge ─────────────────────────────────────────────────────


class TestGatewayBridge:
    def _make_bridge(self):
        from theswarm.presentation.web.server import GatewayBridge
        return GatewayBridge()

    def test_callback_token_generated(self):
        bridge = self._make_bridge()
        assert len(bridge.callback_token) > 20

    async def test_register_and_route_event(self):
        bridge = self._make_bridge()
        received = []

        async def handler(event):
            received.append(event)

        bridge.register("test_event", handler)

        event = MagicMock()
        event.event_type = "test_event"
        await bridge.route_event(event)
        assert len(received) == 1

    async def test_route_event_unregistered_type(self):
        bridge = self._make_bridge()
        event = MagicMock()
        event.event_type = "unknown"
        # Should not raise
        await bridge.route_event(event)

    def test_swarm_po_cycle_state(self):
        bridge = self._make_bridge()
        assert not bridge.swarm_po_is_cycle_running()
        assert bridge.swarm_po_current_phase() == "unknown"

        bridge._swarm_po_cycle_running = True
        bridge._swarm_po_current_phase = "dev"
        assert bridge.swarm_po_is_cycle_running()
        assert bridge.swarm_po_current_phase() == "dev"

    async def test_route_dm_no_chat(self):
        bridge = self._make_bridge()
        bridge._swarm_po_chat = None
        # Should not raise
        await bridge.route_dm_event("swarm_po", "hello", "user1")

    async def test_route_dm_wrong_bot(self):
        bridge = self._make_bridge()
        bridge._swarm_po_chat = MagicMock()
        # Should silently return for non-swarm_po bots
        await bridge.route_dm_event("other_bot", "hello", "user1")


# ── KeywordNLU ────────────────────────────────────────────────────────


class TestKeywordNLU:
    def _make_nlu(self):
        from theswarm.presentation.web.server import _KeywordNLU
        return _KeywordNLU()

    async def test_ping(self):
        nlu = self._make_nlu()
        intent = await nlu.parse_intent("ping", "bot", [])
        assert intent.action == "ping"

    async def test_help(self):
        nlu = self._make_nlu()
        intent = await nlu.parse_intent("help", "bot", [])
        assert intent.action == "help"

    async def test_run_cycle(self):
        nlu = self._make_nlu()
        intent = await nlu.parse_intent("go", "bot", [])
        assert intent.action == "run_cycle"

    async def test_feature_description(self):
        nlu = self._make_nlu()
        intent = await nlu.parse_intent("I want a dashboard with charts", "bot", [])
        assert intent.action == "create_stories"

    async def test_unknown_short(self):
        nlu = self._make_nlu()
        intent = await nlu.parse_intent("xyz", "bot", [])
        assert intent.action == "unknown"


# ── _connect_mattermost ──────────────────────────────────────────────


class TestConnectMattermost:
    async def test_no_config_returns_none(self):
        from theswarm.presentation.web.server import _connect_mattermost
        from theswarm_common.config import MattermostConfig

        result = await _connect_mattermost(MattermostConfig(base_url="", bot_token=""))
        assert result is None

    async def test_success_returns_adapter(self):
        from theswarm.presentation.web.server import _connect_mattermost
        from theswarm_common.config import MattermostConfig

        config = MattermostConfig(base_url="https://mm.test", bot_token="tok")
        mock_adapter = AsyncMock()
        with patch("theswarm_common.chat.mattermost.MattermostAdapter", return_value=mock_adapter):
            result = await _connect_mattermost(config, label="test")
        assert result is mock_adapter

    async def test_failure_returns_none(self):
        from theswarm.presentation.web.server import _connect_mattermost
        from theswarm_common.config import MattermostConfig

        config = MattermostConfig(base_url="https://mm.test", bot_token="tok")
        mock_adapter = AsyncMock()
        mock_adapter.connect.side_effect = ConnectionError("refused")
        with patch("theswarm_common.chat.mattermost.MattermostAdapter", return_value=mock_adapter):
            result = await _connect_mattermost(config, label="test")
        assert result is None


# ── _load_settings ───────────────────────────────────────────────────


class TestLoadSettings:
    def test_defaults(self, tmp_path, monkeypatch):
        yaml_file = tmp_path / "theswarm.yaml"
        yaml_file.write_text("mattermost:\n  base_url: https://mm.test\n")
        monkeypatch.chdir(tmp_path)

        with patch.dict(os.environ, {}, clear=True):
            from theswarm.presentation.web.server import _load_settings
            # Patch the yaml path
            with patch("theswarm.presentation.web.server._load_settings") as mock_load:
                # Just test the function can be imported
                pass

    def test_env_mm_token(self, tmp_path):
        yaml_file = tmp_path / "theswarm.yaml"
        yaml_file.write_text("agents:\n  swarm_po:\n    enabled: true\n")

        with patch.dict(os.environ, {"SWARM_PO_MATTERMOST_TOKEN": "tok-abc"}, clear=True):
            from theswarm.presentation.web.server import _load_settings
            # The function reads theswarm.yaml from cwd, so we'd need to chdir
            # This is tested more thoroughly in test_main.py


# ── CLI run-cycle command ────────────────────────────────────────────


class TestRunCycleParser:
    def test_run_cycle_command(self):
        from theswarm.presentation.cli.main import create_parser
        parser = create_parser()
        args = parser.parse_args(["run-cycle"])
        assert args.command == "run-cycle"
        assert not args.dev_only
        assert not args.techlead_only

    def test_run_cycle_dev_only(self):
        from theswarm.presentation.cli.main import create_parser
        parser = create_parser()
        args = parser.parse_args(["run-cycle", "--dev-only"])
        assert args.dev_only

    def test_run_cycle_techlead_only(self):
        from theswarm.presentation.cli.main import create_parser
        parser = create_parser()
        args = parser.parse_args(["run-cycle", "--techlead-only"])
        assert args.techlead_only


# ── __main__.py entry point ──────────────────────────────────────────


class TestEntryPoint:
    def test_no_args_calls_serve(self):
        """No args should delegate to serve command."""
        with patch("theswarm.presentation.cli.main.main") as mock_main:
            import theswarm.__main__ as entry
            # Reset the module to use our mock
            with patch("theswarm.__main__.sys") as mock_sys:
                mock_sys.argv = ["theswarm"]
                entry.main()
                mock_main.assert_called_once_with(["serve"])

    def test_legacy_cycle_flag(self):
        """--cycle flag should translate to run-cycle command."""
        with patch("theswarm.presentation.cli.main.main") as mock_main:
            import theswarm.__main__ as entry
            with patch("theswarm.__main__.sys") as mock_sys:
                mock_sys.argv = ["theswarm", "--cycle"]
                entry.main()
                mock_main.assert_called_once_with(["run-cycle"])

    def test_legacy_dev_only_flag(self):
        with patch("theswarm.presentation.cli.main.main") as mock_main:
            import theswarm.__main__ as entry
            with patch("theswarm.__main__.sys") as mock_sys:
                mock_sys.argv = ["theswarm", "--dev-only"]
                entry.main()
                mock_main.assert_called_once_with(["run-cycle", "--dev-only"])

    def test_v2_commands_pass_through(self):
        """v2 commands should pass through directly."""
        with patch("theswarm.presentation.cli.main.main") as mock_main:
            import theswarm.__main__ as entry
            with patch("theswarm.__main__.sys") as mock_sys:
                mock_sys.argv = ["theswarm", "projects", "list"]
                entry.main()
                mock_main.assert_called_once_with(["projects", "list"])
