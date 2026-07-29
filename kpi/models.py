"""Typed KPI models for the prior-auth agent.

Every KPI is optional at the report level. When a KPI cannot be derived
honestly from the recorded run, the report omits the value and records a
reason in `not_computed` instead of estimating one.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class UnmeasuredKpi(BaseModel):
    """A KPI the report deliberately does not put a number on."""

    name: str
    reason: str


class KpiScope(BaseModel):
    """Honest scope statement carried inside the artifact itself."""

    source_results_path: str
    split_name: str
    n_decisions: int
    planner_model: str | None = None
    data_kind: str = "synthetic cases with human-confirmed labels"
    execution: str = (
        "single machine, single process, cases executed sequentially (concurrency 1)"
    )
    maturity: str = "demo scope"
    caveats: list[str] = Field(default_factory=list)


class ThroughputKpi(BaseModel):
    """Decisions completed per unit time."""

    n_decisions: int
    total_wall_clock_s: float
    decisions_per_minute: float
    decisions_per_hour: float
    concurrency: int = 1
    method: str


class QualityKpi(BaseModel):
    """Decision quality, bound to the eval harness rather than recomputed."""

    metric: str = "macro_f1"
    macro_f1: float
    accuracy: float
    n_decisions: int
    per_class_f1: dict[str, float] = Field(default_factory=dict)
    source: str
    method: str


class CostKpi(BaseModel):
    """Planner token cost per decision."""

    n_decisions_with_usage: int
    total_input_tokens: int
    total_output_tokens: int
    mean_tokens_per_decision: float
    mean_usd_per_decision: float
    total_usd: float
    projected_usd_per_1000_decisions: float
    pricing_basis: str
    method: str


class HumanInterventionKpi(BaseModel):
    """Share of decisions that stop for a human or a deterministic guardrail."""

    n_decisions: int
    n_intervened: int
    rate: float
    n_approval_gate: int
    n_guardrail: int
    n_both: int
    definition: str
    method: str


class CycleTimeKpi(BaseModel):
    """End-to-end wall clock per decision."""

    n_decisions: int
    p50_s: float
    p95_s: float
    mean_s: float
    min_s: float
    max_s: float
    method: str


class KpiReport(BaseModel):
    """The full KPI artifact for one recorded evaluation run."""

    scope: KpiScope
    throughput: ThroughputKpi | None = None
    quality: QualityKpi | None = None
    cost: CostKpi | None = None
    human_intervention: HumanInterventionKpi | None = None
    cycle_time: CycleTimeKpi | None = None
    not_computed: list[UnmeasuredKpi] = Field(default_factory=list)
    not_measured: list[UnmeasuredKpi] = Field(default_factory=list)
