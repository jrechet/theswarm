"""Tests for theswarm.cycle_log — read/append cycle history."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from theswarm.cycle_log import append_cycle_log, read_cycle_history


class TestReadCycleHistory:
    async def test_valid_jsonl(self, mock_github_client):
        lines = [
            json.dumps({"date": "2025-01-01", "cost_usd": 1.5, "prs_opened": 2}),
            json.dumps({"date": "2025-01-02", "cost_usd": 2.0, "prs_opened": 1}),
        ]
        mock_github_client.get_file_content = AsyncMock(return_value="\n".join(lines))

        result = await read_cycle_history(mock_github_client, limit=50)

        assert len(result) == 2
        # Most recent first (reversed)
        assert result[0]["date"] == "2025-01-02"
        assert result[1]["date"] == "2025-01-01"

    async def test_empty_file(self, mock_github_client):
        mock_github_client.get_file_content = AsyncMock(return_value="")

        result = await read_cycle_history(mock_github_client, limit=50)

        assert result == []

    async def test_missing_file_returns_empty(self, mock_github_client):
        mock_github_client.get_file_content = AsyncMock(
            side_effect=FileNotFoundError("not found")
        )

        result = await read_cycle_history(mock_github_client, limit=50)

        assert result == []

    async def test_malformed_lines_skipped(self, mock_github_client):
        content = (
            json.dumps({"date": "2025-01-01", "ok": True})
            + "\n"
            + "this is not json\n"
            + json.dumps({"date": "2025-01-03", "ok": True})
        )
        mock_github_client.get_file_content = AsyncMock(return_value=content)

        result = await read_cycle_history(mock_github_client, limit=50)

        assert len(result) == 2
        assert result[0]["date"] == "2025-01-03"
        assert result[1]["date"] == "2025-01-01"

    async def test_limit_parameter(self, mock_github_client):
        lines = [json.dumps({"date": f"2025-01-{i:02d}"}) for i in range(1, 11)]
        mock_github_client.get_file_content = AsyncMock(return_value="\n".join(lines))

        result = await read_cycle_history(mock_github_client, limit=3)

        assert len(result) == 3
        # Should return last 3, reversed
        assert result[0]["date"] == "2025-01-10"
        assert result[2]["date"] == "2025-01-08"


class TestAppendCycleLog:
    async def test_stub_mode_skips(self):
        config = MagicMock()
        config.is_real_mode = False

        ok = await append_cycle_log(config, {"date": "2025-01-01"})

        assert ok is True
