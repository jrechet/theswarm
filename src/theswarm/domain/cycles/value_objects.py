"""Value objects for the Cycles bounded context."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import uuid4


class CycleStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PhaseStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class CycleId:
    """Unique cycle identifier."""

    value: str

    @classmethod
    def generate(cls) -> CycleId:
        return cls(value=uuid4().hex[:12])

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class TokenUsage:
    """Token usage for a single agent or phase."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


@dataclass(frozen=True)
class Budget:
    """Token budget for one agent role."""

    role: str
    limit: int
    used: int = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def percent_used(self) -> float:
        if self.limit == 0:
            return 0.0
        return min(100.0, (self.used / self.limit) * 100)

    @property
    def exceeded(self) -> bool:
        return self.used > self.limit

    def with_usage(self, tokens: int) -> Budget:
        return Budget(role=self.role, limit=self.limit, used=self.used + tokens)
