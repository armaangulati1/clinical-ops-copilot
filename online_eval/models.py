"""Typed records for the online evaluation loop.

The chain is: ``SpanRecord`` (what the tracer emitted) -> ``TracedRun`` (one
agent run reconstructed from its spans) -> ``ScoredRun`` (that run plus the
scores the loop can compute) -> ``WindowMetrics`` (an aggregate over a window)
-> ``DriftFinding`` / ``AlertEvent`` -> ``CycleRecord`` (one persisted loop
execution).

Every metric that cannot be computed honestly is ``None`` with a reason in
``notes``, following the same rule the KPI layer already uses: an absent
measurement is reported as absent, never estimated.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

NANOS_PER_MS = 1_000_000


class SpanRecord(BaseModel):
    """One OpenInference span, flattened for storage.

    This is the wire format of the trace store. It carries exactly the fields
    needed to reconstruct a run, so the store can be replayed without an OTel
    SDK and without a Phoenix server.
    """

    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    name: str
    start_unix_ns: int
    end_unix_ns: int
    attributes: dict[str, Any] = Field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        return (self.end_unix_ns - self.start_unix_ns) / NANOS_PER_MS


class TracedRun(BaseModel):
    """One agent run as the eval loop sees it: from traces only.

    Nothing here comes from the eval dataset. Ground truth is joined later, and
    only for the adjudicated subset, which is what keeps this reconstruction
    honest about what a trace can actually tell you.
    """

    trace_id: str
    case_id: str
    observed_at: datetime
    predicted_action: str
    confidence: float
    latency_ms: float
    tool_call_count: int = 0
    guardrail_triggered: bool = False
    needs_review_count: int = 0


class ScoredRun(BaseModel):
    """A traced run plus the scores the loop could compute for it."""

    run: TracedRun
    label_action: str | None = None
    correct: bool | None = None
    low_confidence: bool = False

    @property
    def is_labeled(self) -> bool:
        return self.label_action is not None


class WindowMetrics(BaseModel):
    """Aggregate metrics over a window of scored runs."""

    window_id: str
    computed_at: datetime
    n_runs: int
    n_labeled: int
    action_counts: dict[str, int] = Field(default_factory=dict)
    action_distribution: dict[str, float] = Field(default_factory=dict)
    mean_confidence: float = 0.0
    low_confidence_rate: float = 0.0
    guardrail_rate: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    macro_f1: float | None = None
    accuracy: float | None = None
    notes: list[str] = Field(default_factory=list)

    @property
    def label_coverage(self) -> float:
        if self.n_runs == 0:
            return 0.0
        return self.n_labeled / self.n_runs


class DriftFinding(BaseModel):
    """One comparison of the current window against the baseline window.

    ``comparable`` is separate from ``breached`` on purpose. A detector that
    could not run (too few runs, no baseline, no labels) must not report
    ``breached=False``, because "we did not look" and "we looked and it is fine"
    are different states and collapsing them is how a monitor goes quietly
    blind.
    """

    metric: str
    method: str
    comparable: bool
    breached: bool = False
    baseline_value: float | None = None
    current_value: float | None = None
    delta: float | None = None
    threshold: float | None = None
    note: str = ""


class AlertEvent(BaseModel):
    """An alert condition the loop raised. Written to the alert log."""

    cycle_id: str
    raised_at: datetime
    severity: str
    metric: str
    message: str


class CycleRecord(BaseModel):
    """One execution of the loop, persisted so a trend exists over time."""

    cycle_id: str
    started_at: datetime
    finished_at: datetime
    n_sampled: int
    n_scored: int
    cursor_before_ns: int
    cursor_after_ns: int
    cycle_window: WindowMetrics | None = None
    rolling_window: WindowMetrics | None = None
    baseline_window_id: str | None = None
    findings: list[DriftFinding] = Field(default_factory=list)
    alerts: list[AlertEvent] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
