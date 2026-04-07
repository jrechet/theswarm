"""Token usage tracking per agent per cycle."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TokenRecord:
    agent: str
    tokens: int
    cost_usd: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TokenTracker:
    """Accumulates token usage across a cycle and prints a summary."""
    records: list[TokenRecord] = field(default_factory=list)

    def record(self, agent: str, tokens: int, cost_usd: float = 0.0) -> TokenRecord:
        rec = TokenRecord(agent=agent, tokens=tokens, cost_usd=cost_usd)
        self.records.append(rec)
        print(f"  -> {agent}: {tokens:,} tokens (${cost_usd:.4f})")
        return rec

    @property
    def total_tokens(self) -> int:
        return sum(r.tokens for r in self.records)

    @property
    def total_cost(self) -> float:
        return sum(r.cost_usd for r in self.records)

    def print_summary(self) -> None:
        total_t = self.total_tokens
        total_c = self.total_cost
        if total_t == 0:
            print("\nNo tokens consumed (stub run).")
            return

        print(f"\nTokens total : {total_t:,}")
        print(f"Cost LLM     : ${total_c:.2f}")
        print(f"Cost/month   : ~${total_c * 30:.0f} (projected)")
        print("\nBreakdown by agent:")
        for r in sorted(self.records, key=lambda x: x.tokens, reverse=True):
            bar = "#" * int(r.tokens / total_t * 20) if total_t else ""
            print(f"  {r.agent:<25} {bar:<20} {r.tokens:>10,} tokens")
