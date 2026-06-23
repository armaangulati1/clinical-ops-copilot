"""Latency and cost summary statistics."""

from __future__ import annotations

from pydantic import BaseModel


class LatencySummary(BaseModel):
    p50_ms: float
    p95_ms: float
    mean_ms: float
    n_cases: int


class CostSummary(BaseModel):
    mean_usd_per_case: float
    total_usd: float
    n_cases: int


def percentile(values: list[float], p: float) -> float:
    """Return the p-th percentile (0-100) using linear interpolation."""
    if not values:
        msg = "values must not be empty"
        raise ValueError(msg)
    if not 0 <= p <= 100:
        msg = "p must be between 0 and 100"
        raise ValueError(msg)
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (p / 100) * (len(sorted_values) - 1)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    weight = rank - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def compute_latency_summary(latencies_ms: list[float]) -> LatencySummary:
    if not latencies_ms:
        return LatencySummary(p50_ms=0.0, p95_ms=0.0, mean_ms=0.0, n_cases=0)
    return LatencySummary(
        p50_ms=round(percentile(latencies_ms, 50), 2),
        p95_ms=round(percentile(latencies_ms, 95), 2),
        mean_ms=round(sum(latencies_ms) / len(latencies_ms), 2),
        n_cases=len(latencies_ms),
    )


def compute_cost_summary(costs_usd: list[float]) -> CostSummary:
    if not costs_usd:
        return CostSummary(mean_usd_per_case=0.0, total_usd=0.0, n_cases=0)
    total = sum(costs_usd)
    return CostSummary(
        mean_usd_per_case=round(total / len(costs_usd), 6),
        total_usd=round(total, 6),
        n_cases=len(costs_usd),
    )
