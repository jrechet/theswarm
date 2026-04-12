"""Tests for theswarm.tools.claude — cost estimation, model resolution, result dataclass."""

from __future__ import annotations

import pytest

from theswarm.tools.claude import ClaudeCLI, ClaudeResult, _estimate_cost


class TestEstimateCost:
    def test_sonnet_cost(self):
        # 1M input + 1M output: input $3.00 + output $15.00 = $18.00
        # With 1000 tokens: 3.0 * 1000 / 1_000_000 + 15.0 * 1000 / 1_000_000
        cost = _estimate_cost("claude-sonnet-4-20250514", 1_000_000, 1_000_000)
        assert cost == pytest.approx(18.0, abs=0.01)

    def test_opus_cost(self):
        # 1M input + 1M output: input $15.00 + output $75.00 = $90.00
        cost = _estimate_cost("claude-opus-4-20250514", 1_000_000, 1_000_000)
        assert cost == pytest.approx(90.0, abs=0.01)

    def test_haiku_cost(self):
        # 1M input + 1M output: input $0.80 + output $4.00 = $4.80
        cost = _estimate_cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000)
        assert cost == pytest.approx(4.80, abs=0.01)

    def test_unknown_model_uses_default_rates(self):
        # Default rates: input=3.0, output=15.0 (same as sonnet)
        cost = _estimate_cost("unknown-model-v99", 1_000_000, 1_000_000)
        assert cost == pytest.approx(18.0, abs=0.01)

    def test_zero_tokens(self):
        cost = _estimate_cost("claude-sonnet-4-20250514", 0, 0)
        assert cost == 0.0

    def test_large_token_count(self):
        # 1M input tokens for sonnet: 3.0 * 1M / 1M = $3.00
        # 1M output tokens for sonnet: 15.0 * 1M / 1M = $15.00
        cost = _estimate_cost("claude-sonnet-4-20250514", 1_000_000, 1_000_000)
        assert cost == pytest.approx(18.0, abs=0.01)


class TestResolveModel:
    def test_sonnet_short_name(self):
        cli = ClaudeCLI(model="sonnet")
        assert cli._resolve_model() == "claude-sonnet-4-20250514"

    def test_opus_short_name(self):
        cli = ClaudeCLI(model="opus")
        assert cli._resolve_model() == "claude-opus-4-20250514"

    def test_haiku_short_name(self):
        cli = ClaudeCLI(model="haiku")
        assert cli._resolve_model() == "claude-haiku-4-5-20251001"

    def test_full_model_id_passthrough(self):
        cli = ClaudeCLI(model="claude-sonnet-4-20250514")
        assert cli._resolve_model() == "claude-sonnet-4-20250514"

    def test_unknown_model_passthrough(self):
        cli = ClaudeCLI(model="my-custom-model")
        assert cli._resolve_model() == "my-custom-model"


class TestClaudeResult:
    def test_default_values(self):
        result = ClaudeResult(text="hello")
        assert result.text == "hello"
        assert result.input_tokens == 0
        assert result.output_tokens == 0
        assert result.total_tokens == 0
        assert result.cost_usd == 0.0
        assert result.model == ""

    def test_all_fields(self):
        result = ClaudeResult(
            text="response",
            input_tokens=500,
            output_tokens=200,
            total_tokens=700,
            cost_usd=0.0045,
            model="claude-sonnet-4-20250514",
        )
        assert result.text == "response"
        assert result.input_tokens == 500
        assert result.output_tokens == 200
        assert result.total_tokens == 700
        assert result.cost_usd == pytest.approx(0.0045)
        assert result.model == "claude-sonnet-4-20250514"
