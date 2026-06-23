"""Unit tests for offline eval metric functions."""

from __future__ import annotations

from agent.run_log import RunLog, ToolCallRecord
from evals.metrics.classification import compute_classification_metrics
from evals.metrics.errors import ErrorCategory, classify_decision_error
from evals.metrics.judge_agreement import compute_judge_agreement
from evals.metrics.latency import (
    compute_cost_summary,
    compute_latency_summary,
    percentile,
)
from evals.metrics.trajectory import (
    EXTRACT_TOOL,
    POLICY_TOOL,
    aggregate_trajectory_scores,
    score_trajectory,
)
from schemas.cases import CaseLabel, Difficulty
from schemas.decisions import Decision, DecisionAction, ProposedAction


def test_confusion_matrix_and_macro_f1() -> None:
    y_true = ["submit", "submit", "deny-risk", "request-more-info"]
    y_pred = ["submit", "request-more-info", "deny-risk", "request-more-info"]
    metrics = compute_classification_metrics(y_true, y_pred)
    assert metrics.n_cases == 4
    assert metrics.accuracy == 0.75
    assert metrics.confusion_matrix.cell("submit", "submit") == 1
    assert metrics.confusion_matrix.cell("submit", "request-more-info") == 1
    assert metrics.per_class["deny-risk"].f1 == 1.0
    assert 0 < metrics.macro_f1 < 1


def test_error_taxonomy_missed_missing_field() -> None:
    label = CaseLabel(
        correct_action=DecisionAction.REQUEST_MORE_INFO,
        required_fields_present={"das28_score": False},
        fields_missing=["das28_score"],
        label_rationale="DAS28 not documented in the chart note.",
        difficulty=Difficulty.MEDIUM,
    )
    entry = classify_decision_error(
        case_id="case-007",
        predicted=DecisionAction.SUBMIT,
        truth=DecisionAction.REQUEST_MORE_INFO,
        label=label,
    )
    assert entry is not None
    assert entry.category == ErrorCategory.MISSED_MISSING_FIELD


def test_percentile_and_latency_summary() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 100.0]
    assert percentile(values, 50) == 30.0
    assert percentile(values, 95) >= 80.0
    summary = compute_latency_summary(values)
    assert summary.p50_ms == 30.0
    assert summary.n_cases == 5


def test_cost_summary() -> None:
    summary = compute_cost_summary([0.01, 0.02, 0.03])
    assert summary.total_usd == 0.06
    assert summary.mean_usd_per_case == 0.02


def test_judge_agreement_metrics() -> None:
    human = [5, 4, 3, 4, 5]
    judge = [5, 3, 3, 4, 4]
    metrics = compute_judge_agreement(human, judge)
    assert metrics.n_cases == 5
    assert metrics.exact_agreement_rate == 0.6
    assert metrics.mean_absolute_error == 0.4
    assert metrics.pearson_r is not None


def test_trajectory_scorer_flags_wrong_order() -> None:
    run_log = RunLog(case_id="case-001", drug="Humira", condition="ra")
    run_log.tool_calls = [
        ToolCallRecord(
            tool=POLICY_TOOL,
            arguments_summary={},
            result_summary={},
            duration_ms=1.0,
        ),
        ToolCallRecord(
            tool=EXTRACT_TOOL,
            arguments_summary={},
            result_summary={},
            duration_ms=1.0,
        ),
    ]
    decision = Decision(
        action=DecisionAction.SUBMIT,
        confidence=0.9,
        rationale="All criteria met for this synthetic test case.",
        proposed_action=ProposedAction(
            server="clinic-ops",
            tool="create_task",
            arguments={"title": "Submit"},
        ),
    )
    score = score_trajectory(run_log, decision)
    assert score.correct is False
    assert any("step 1" in reason for reason in score.violations)


def test_trajectory_scorer_accepts_valid_workflow() -> None:
    run_log = RunLog(case_id="case-002", drug="Humira", condition="ra")
    run_log.tool_calls = [
        ToolCallRecord(
            tool=EXTRACT_TOOL,
            arguments_summary={},
            result_summary={},
            duration_ms=1.0,
        ),
        ToolCallRecord(
            tool=POLICY_TOOL,
            arguments_summary={},
            result_summary={},
            duration_ms=1.0,
        ),
    ]
    decision = Decision(
        action=DecisionAction.REQUEST_MORE_INFO,
        confidence=0.7,
        rationale="Missing required policy fields in this synthetic test.",
        proposed_action=ProposedAction(
            server="clinic-ops",
            tool="draft_email",
            arguments={"to": "a@b.com", "subject": "Info", "body": "Need docs"},
        ),
    )
    score = score_trajectory(run_log, decision)
    assert score.correct is True
    assert score.warnings == []
    assert aggregate_trajectory_scores([score]) == 100.0


def test_trajectory_submit_send_email_is_warning_not_failure() -> None:
    run_log = RunLog(case_id="case-003", drug="Humira", condition="ra")
    run_log.tool_calls = [
        ToolCallRecord(
            tool=EXTRACT_TOOL,
            arguments_summary={},
            result_summary={},
            duration_ms=1.0,
        ),
        ToolCallRecord(
            tool=POLICY_TOOL,
            arguments_summary={},
            result_summary={},
            duration_ms=1.0,
        ),
    ]
    decision = Decision(
        action=DecisionAction.SUBMIT,
        confidence=0.9,
        rationale="All criteria met for this synthetic test case.",
        proposed_action=ProposedAction(
            server="clinic-ops",
            tool="send_email",
            arguments={"to": "a@b.com", "subject": "Submit", "body": "Ready"},
        ),
    )
    score = score_trajectory(run_log, decision)
    assert score.correct is True
    assert score.violations == []
    assert score.warnings
