"""Pydantic models for evaluation outputs."""

from __future__ import annotations

from pydantic import BaseModel, Field

from evals.metrics.classification import ClassificationMetrics
from evals.metrics.errors import ErrorTaxonomyEntry
from evals.metrics.judge_agreement import JudgeAgreementMetrics
from evals.metrics.latency import CostSummary, LatencySummary
from evals.metrics.trajectory import TrajectoryScore, TrajectoryViolation
from schemas.run_metrics import PlannerRunMetrics


class CaseEvalResult(BaseModel):
    case_id: str
    predicted_action: str
    truth_action: str
    correct: bool
    trajectory: TrajectoryScore
    planner_metrics: PlannerRunMetrics | None = None
    total_latency_ms: float = 0.0
    drafted_email: str | None = None
    email_subject: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    judge_email_score: int | None = None


class EvalIntegrityNote(BaseModel):
    labels_read_only_in_evals: bool = True
    agent_runtime_reads_labels: bool = False
    seed_data_used_for_case_authoring: bool = True
    caveat: str = Field(
        default=(
            "SEED_SPECS in schemas/seed_data.py informed synthetic case authoring; "
            "final labels in data/labels/labels.json were human-confirmed separately. "
            "Agent prompts and planner logic do not read labels at runtime."
        )
    )


class EvalResults(BaseModel):
    integrity: EvalIntegrityNote = Field(default_factory=EvalIntegrityNote)
    n_cases: int
    classification: ClassificationMetrics
    error_taxonomy: list[ErrorTaxonomyEntry]
    trajectory_correct_pct: float
    trajectory_violations: list[TrajectoryViolation]
    trajectory_warnings: list[TrajectoryViolation] = Field(default_factory=list)
    latency: LatencySummary
    cost: CostSummary
    judge_agreement: JudgeAgreementMetrics | None = None
    judge_validation_n: int = 0
    case_results: list[CaseEvalResult] = Field(default_factory=list)
    planner_model: str | None = None
    notes: list[str] = Field(default_factory=list)
