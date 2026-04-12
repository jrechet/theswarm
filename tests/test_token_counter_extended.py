"""Extended tests for theswarm.token_counter — edge cases and summary output."""

from __future__ import annotations

import pytest

from theswarm.token_counter import TokenRecord, TokenTracker


class TestZeroTokenRecord:
    def test_zero_token_record(self):
        rec = TokenRecord(agent="idle", tokens=0, cost_usd=0.0)
        assert rec.agent == "idle"
        assert rec.tokens == 0
        assert rec.cost_usd == 0.0

    def test_tracker_with_zero_record(self):
        tracker = TokenTracker()
        tracker.record("idle", 0, cost_usd=0.0)

        assert tracker.total_tokens == 0
        assert tracker.total_cost == 0.0
        assert len(tracker.records) == 1


class TestPrintSummary:
    def test_no_records_stub_output(self, capsys):
        tracker = TokenTracker()

        tracker.print_summary()

        captured = capsys.readouterr()
        assert "No tokens consumed (stub run)" in captured.out

    def test_zero_token_records_stub_output(self, capsys):
        tracker = TokenTracker()
        tracker.record("idle", 0, cost_usd=0.0)

        tracker.print_summary()

        captured = capsys.readouterr()
        assert "No tokens consumed (stub run)" in captured.out

    def test_with_records_shows_breakdown(self, capsys):
        tracker = TokenTracker()
        tracker.record("dev", 100_000, cost_usd=0.30)
        tracker.record("qa", 50_000, cost_usd=0.15)

        tracker.print_summary()

        captured = capsys.readouterr()
        assert "Tokens total" in captured.out
        assert "150,000" in captured.out
        assert "Cost LLM" in captured.out
        assert "$0.45" in captured.out
        assert "Cost/month" in captured.out
        assert "Breakdown by agent" in captured.out
        assert "dev" in captured.out
        assert "qa" in captured.out

    def test_breakdown_sorted_by_tokens_descending(self, capsys):
        tracker = TokenTracker()
        tracker.record("small", 10_000, cost_usd=0.03)
        tracker.record("large", 200_000, cost_usd=0.60)
        tracker.record("medium", 50_000, cost_usd=0.15)

        tracker.print_summary()

        captured = capsys.readouterr()
        lines = [l for l in captured.out.splitlines() if l.strip().startswith(("large", "medium", "small"))]
        assert len(lines) == 3
        assert "large" in lines[0]
        assert "medium" in lines[1]
        assert "small" in lines[2]
