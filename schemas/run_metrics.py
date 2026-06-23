"""Planner usage and cost metrics captured during agent runs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class PlannerRunMetrics(BaseModel):
    latency_ms: float = Field(default=0.0, ge=0.0)
    usage: TokenUsage = Field(default_factory=TokenUsage)
    estimated_cost_usd: float = Field(default=0.0, ge=0.0)
    model: str | None = None


# Claude Sonnet 4.5 list pricing (USD per token) — update when model pricing changes.
INPUT_COST_PER_TOKEN_USD = 3.0 / 1_000_000
OUTPUT_COST_PER_TOKEN_USD = 15.0 / 1_000_000


def estimate_planner_cost_usd(
    *,
    input_tokens: int,
    output_tokens: int,
) -> float:
    return round(
        input_tokens * INPUT_COST_PER_TOKEN_USD
        + output_tokens * OUTPUT_COST_PER_TOKEN_USD,
        6,
    )
