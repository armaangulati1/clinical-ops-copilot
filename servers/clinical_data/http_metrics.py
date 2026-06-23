"""In-memory HTTP request metrics for the clinical-data server."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100.0)
    floor = int(k)
    ceil = min(floor + 1, len(sorted_vals) - 1)
    if floor == ceil:
        return sorted_vals[floor]
    return sorted_vals[floor] + (sorted_vals[ceil] - sorted_vals[floor]) * (k - floor)


@dataclass
class HttpMetrics:
    """Thread-safe counters and latency samples for MCP HTTP requests."""

    started_at: float = field(default_factory=time.monotonic)
    request_count: int = 0
    error_count: int = 0
    _latencies_ms: list[float] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, *, latency_ms: float, is_error: bool) -> None:
        with self._lock:
            self.request_count += 1
            if is_error:
                self.error_count += 1
            self._latencies_ms.append(latency_ms)

    def uptime_seconds(self) -> float:
        return round(time.monotonic() - self.started_at, 2)

    def snapshot(self) -> dict[str, float | int]:
        with self._lock:
            latencies = list(self._latencies_ms)
            request_count = self.request_count
            error_count = self.error_count
        if not latencies:
            return {
                "request_count": request_count,
                "error_count": error_count,
                "latency_p50_ms": 0.0,
                "latency_p95_ms": 0.0,
            }
        return {
            "request_count": request_count,
            "error_count": error_count,
            "latency_p50_ms": round(_percentile(latencies, 50), 2),
            "latency_p95_ms": round(_percentile(latencies, 95), 2),
        }


METRICS = HttpMetrics()
