"""Server configuration for clinic-ops MCP."""

from __future__ import annotations

import os
from dataclasses import dataclass

LATENCY_MIN_ENV = "CLINIC_OPS_LATENCY_MIN"
LATENCY_MAX_ENV = "CLINIC_OPS_LATENCY_MAX"
FAILURE_RATE_ENV = "CLINIC_OPS_FAILURE_RATE"
RNG_SEED_ENV = "CLINIC_OPS_RNG_SEED"
MOCK_TIMEOUT_ENV = "CLINIC_OPS_MOCK_TIMEOUT_SECONDS"
MAX_ATTEMPTS_ENV = "CLINIC_OPS_MAX_ATTEMPTS"
BACKOFF_MIN_ENV = "CLINIC_OPS_BACKOFF_MIN"
BACKOFF_MAX_ENV = "CLINIC_OPS_BACKOFF_MAX"


@dataclass(frozen=True)
class ServerConfig:
    """Runtime configuration for mocked clinic-ops externals."""

    latency_min_seconds: float = 0.5
    latency_max_seconds: float = 3.0
    failure_rate: float = 0.0
    rng_seed: int | None = None
    mock_timeout_seconds: float = 30.0
    max_attempts: int = 5
    backoff_min_seconds: float = 0.1
    backoff_max_seconds: float = 2.0


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return float(raw)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return int(raw)


def load_config(**overrides: float | int | None) -> ServerConfig:
    """Load config from environment with optional test overrides."""
    seed_raw = os.environ.get(RNG_SEED_ENV)
    rng_seed = int(seed_raw) if seed_raw is not None else None
    if "rng_seed" in overrides:
        rng_seed = overrides["rng_seed"]  # type: ignore[assignment]

    return ServerConfig(
        latency_min_seconds=float(
            overrides.get("latency_min_seconds") or _float_env(LATENCY_MIN_ENV, 0.5)
        ),
        latency_max_seconds=float(
            overrides.get("latency_max_seconds") or _float_env(LATENCY_MAX_ENV, 3.0)
        ),
        failure_rate=float(
            overrides.get("failure_rate") or _float_env(FAILURE_RATE_ENV, 0.0)
        ),
        rng_seed=rng_seed,
        mock_timeout_seconds=float(
            overrides.get("mock_timeout_seconds") or _float_env(MOCK_TIMEOUT_ENV, 30.0)
        ),
        max_attempts=int(
            overrides.get("max_attempts") or _int_env(MAX_ATTEMPTS_ENV, 5)
        ),
        backoff_min_seconds=float(
            overrides.get("backoff_min_seconds") or _float_env(BACKOFF_MIN_ENV, 0.1)
        ),
        backoff_max_seconds=float(
            overrides.get("backoff_max_seconds") or _float_env(BACKOFF_MAX_ENV, 2.0)
        ),
    )
