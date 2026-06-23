"""Aggregate per-case eval artifacts into report-level metrics."""

from __future__ import annotations

from evals.metrics.classification import compute_classification_metrics
from evals.metrics.errors import ErrorTaxonomyEntry, classify_decision_error
from evals.metrics.judge_agreement import JudgeAgreementMetrics, compute_judge_agreement
from evals.metrics.latency import compute_cost_summary, compute_latency_summary
from evals.metrics.trajectory import TrajectoryViolation, aggregate_trajectory_scores
from evals.models import CaseEvalResult, EvalResults
from evals.runner import aggregate_planner_metrics
from schemas.decisions import DecisionAction
from schemas.loader import DatasetEntry


def build_eval_results(
    entries: list[DatasetEntry],
    case_results: list[CaseEvalResult],
    *,
    judge_agreement: JudgeAgreementMetrics | None = None,
    judge_validation_n: int = 0,
    planner_model: str | None = None,
    notes: list[str] | None = None,
) -> EvalResults:
    labels_by_id = {entry.case.case_id: entry.label for entry in entries}
    y_true = [result.truth_action for result in case_results]
    y_pred = [result.predicted_action for result in case_results]
    classification = compute_classification_metrics(y_true, y_pred)

    taxonomy: list[ErrorTaxonomyEntry] = []
    for result in case_results:
        if result.correct:
            continue
        label = labels_by_id[result.case_id]
        entry = classify_decision_error(
            case_id=result.case_id,
            predicted=DecisionAction(result.predicted_action),
            truth=DecisionAction(result.truth_action),
            label=label,
        )
        if entry is not None:
            taxonomy.append(entry)

    violations = [
        TrajectoryViolation(case_id=score.case_id, reason=reason)
        for score in (result.trajectory for result in case_results)
        for reason in score.violations
    ]
    warnings = [
        TrajectoryViolation(case_id=score.case_id, reason=reason)
        for score in (result.trajectory for result in case_results)
        for reason in score.warnings
    ]
    latencies, costs = aggregate_planner_metrics(case_results)

    return EvalResults(
        n_cases=len(case_results),
        classification=classification,
        error_taxonomy=taxonomy,
        trajectory_correct_pct=aggregate_trajectory_scores(
            [result.trajectory for result in case_results]
        ),
        trajectory_violations=violations,
        trajectory_warnings=warnings,
        latency=compute_latency_summary(latencies),
        cost=compute_cost_summary(costs),
        judge_agreement=judge_agreement,
        judge_validation_n=judge_validation_n,
        case_results=case_results,
        planner_model=planner_model,
        notes=notes or [],
    )


def human_judge_agreement(
    human_scores: dict[str, int],
    case_results: list[CaseEvalResult],
) -> JudgeAgreementMetrics | None:
    paired_human: list[int] = []
    paired_judge: list[int] = []
    for result in case_results:
        if result.case_id not in human_scores:
            continue
        if result.judge_email_score is None:
            continue
        paired_human.append(human_scores[result.case_id])
        paired_judge.append(result.judge_email_score)
    if not paired_human:
        return None
    return compute_judge_agreement(paired_human, paired_judge)
