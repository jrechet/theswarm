"""Tests for the capture_demo_screenshots QA node."""

from __future__ import annotations

import pytest

from theswarm.agents.qa import capture_demo_screenshots
from theswarm.agents.base import stub_result
from theswarm.config import Role


class TestCaptureStubMode:
    """In stub mode (no claude/workspace), the node returns a stub result."""

    async def test_stub_when_no_workspace(self):
        state = {"claude": None, "workspace": None}
        result = await capture_demo_screenshots(state)
        assert "result" in result
        assert "capture" in result["result"].lower() or "screenshot" in result["result"].lower()

    async def test_stub_when_no_claude(self):
        state = {"claude": None, "workspace": "/tmp/fake"}
        result = await capture_demo_screenshots(state)
        assert "result" in result
