"""Unit tests for the operational KPI computations.

The KPI layer must do two things well: compute the five deployment KPIs
correctly from a recorded run, and refuse to produce a number when the run
does not support one. Both halves are tested here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from evals.metrics.classification import compute_classification_metrics
from evals.metrics.latency import compute_cost_summary, compute_latency_summary
from evals.metrics.trajectory import TrajectoryScore
from evals.models import CaseEvalResult, EvalResults
from kpi.compute import (
    compute_cost,
    compute_cycle_time,
    compute_human_intervention,
    compute_kpi_report,
    compute_quality,
    compute_throughput,
)
from kpi.models import (
    CostKpi,
    CycleTimeKpi,
    HumanInterventionKpi,
    QualityKpi,
    ThroughputKpi,
    UnmeasuredKpi,
)
from schemas.run_metrics import PlannerRunMetrics, TokenUsage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCKED_RESULTS = PROJECT_ROOT / "evals/results/locked_test.json"


def _case(
    case_id: str,
    *,
    predicted: str,
    truth: str,
    latency_ms: float = 1000.0,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    approval_required: bool | None = False,
    guardrail_triggered: bool | None = False,
) -> CaseEvalResult:
    metrics: PlannerRunMetrics | None = None
    if input_tokens is not None and output_tokens is not None:
        metrics = PlannerRunMetrics(
            latency_ms=latency_ms,
            usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            estimated_cost_usd=0.0,
            model="test-model",
        )
    return CaseEvalResult(
        case_id=case_id,
        predicted_action=predicted,
        truth_action=truth,
        correct=predicted == truth,
        trajectory=TrajectoryScore(case_id=case_id, correct=True),
        planner_metrics=metrics,
        total_latency_ms=latency_ms,
        approval_required=approval_required,
        guardrail_triggered=guardrail_triggered,
    )


def _results(case_results: list[CaseEvalResult]) -> EvalResults:
    classification = compute_classification_metrics(
        [result.truth_action for result in case_results],
        [result.predicted_action for result in case_results],
    )
    latencies = [result.total_latency_ms for result in case_results]
    return EvalResults(
        n_cases=len(case_results),
        classification=classification,
        error_taxonomy=[],
        trajectory_correct_pct=100.0,
        trajectory_violations=[],
        latency=compute_latency_summary(latencies),
        cost=compute_cost_summary([0.0 for _ in case_results]),
        case_results=case_results,
        planner_model="test-model",
    )


def test_throughput_is_decisions_over_summed_wall_clock() -> None:
    results = _results(
        [
            _case("a", predicted="submit", truth="submit", latency_ms=10_000.0),
            _case("b", predicted="submit", truth="submit", latency_ms=20_000.0),
        ]
    )
    throughput = compute_throughput(results)
    assert isinstance(throughput, ThroughputKpi)
    # 2 decisions in 30 seconds of serial wall clock is 4 per minute.
    assert throughput.total_wall_clock_s == pytest.approx(30.0)
    assert throughput.decisions_per_minute == pytest.approx(4.0)
    assert throughput.decisions_per_hour == pytest.approx(240.0)
    assert throughput.concurrency == 1


def test_throughput_abstains_when_no_wall_clock_recorded() -> None:
    results = _results([_case("a", predicted="submit", truth="submit", latency_ms=0.0)])
    throughput = compute_throughput(results)
    assert isinstance(throughput, UnmeasuredKpi)
    assert "wall clock" in throughput.reason


def test_quality_is_bound_to_the_harness_and_not_recomputed() -> None:
    """The KPI layer must echo the eval harness, never derive a rival number."""
    results = _results(
        [
            _case("a", predicted="submit", truth="submit"),
            _case("b", predicted="submit", truth="deny-risk"),
        ]
    )
    quality = compute_quality(results, source_results_path="fake.json")
    assert isinstance(quality, QualityKpi)
    assert quality.macro_f1 == results.classification.macro_f1
    assert quality.accuracy == results.classification.accuracy
    assert quality.n_decisions == results.classification.n_cases


def test_cost_sums_recorded_tokens_and_prices_them() -> None:
    results = _results(
        [
            _case(
                "a",
                predicted="submit",
                truth="submit",
                input_tokens=1_000_000,
                output_tokens=0,
            ),
            _case(
                "b",
                predicted="submit",
                truth="submit",
                input_tokens=0,
                output_tokens=1_000_000,
            ),
        ]
    )
    cost = compute_cost(results)
    assert isinstance(cost, CostKpi)
    assert cost.total_input_tokens == 1_000_000
    assert cost.total_output_tokens == 1_000_000
    assert cost.mean_tokens_per_decision == pytest.approx(1_000_000.0)
    # $3 per million input plus $15 per million output, over two decisions.
    assert cost.total_usd == pytest.approx(18.0)
    assert cost.mean_usd_per_decision == pytest.approx(9.0)
    assert cost.projected_usd_per_1000_decisions == pytest.approx(9000.0)


def test_cost_abstains_when_no_planner_metrics_were_recorded() -> None:
    results = _results([_case("a", predicted="submit", truth="submit")])
    cost = compute_cost(results)
    assert isinstance(cost, UnmeasuredKpi)
    assert "no planner token usage" in cost.reason.lower()


def test_cost_abstains_on_a_zero_token_stub_run() -> None:
    """A stub planner records metrics with zero tokens.

    Pricing that would yield $0.00 per decision, which reads as a measured
    figure. The harness must refuse it instead.
    """
    results = _results(
        [
            _case(
                "a",
                predicted="submit",
                truth="submit",
                input_tokens=0,
                output_tokens=0,
            )
        ]
    )
    cost = compute_cost(results)
    assert isinstance(cost, UnmeasuredKpi)
    assert "zero tokens" in cost.reason


def test_human_intervention_is_the_union_of_gate_and_guardrail() -> None:
    results = _results(
        [
            _case(
                "gate-only",
                predicted="submit",
                truth="submit",
                approval_required=True,
                guardrail_triggered=False,
            ),
            _case(
                "guardrail-only",
                predicted="request-more-info",
                truth="request-more-info",
                approval_required=False,
                guardrail_triggered=True,
            ),
            _case(
                "both",
                predicted="request-more-info",
                truth="request-more-info",
                approval_required=True,
                guardrail_triggered=True,
            ),
            _case(
                "neither",
                predicted="request-more-info",
                truth="request-more-info",
                approval_required=False,
                guardrail_triggered=False,
            ),
        ]
    )
    intervention = compute_human_intervention(results)
    assert isinstance(intervention, HumanInterventionKpi)
    assert intervention.n_approval_gate == 2
    assert intervention.n_guardrail == 2
    assert intervention.n_both == 1
    # Union is 3 of 4, not the 4 that summing the two components would give.
    assert intervention.n_intervened == 3
    assert intervention.rate == pytest.approx(0.75)


def test_human_intervention_abstains_when_signals_were_not_recorded() -> None:
    results = _results(
        [
            _case(
                "a",
                predicted="submit",
                truth="submit",
                approval_required=None,
                guardrail_triggered=None,
            ),
            _case("b", predicted="submit", truth="submit"),
        ]
    )
    intervention = compute_human_intervention(results)
    assert isinstance(intervention, UnmeasuredKpi)
    assert "1 of 2" in intervention.reason


def test_cycle_time_percentiles_use_end_to_end_wall_clock() -> None:
    latencies = [1000.0, 2000.0, 3000.0, 4000.0, 100_000.0]
    results = _results(
        [
            _case(f"c{i}", predicted="submit", truth="submit", latency_ms=value)
            for i, value in enumerate(latencies)
        ]
    )
    cycle_time = compute_cycle_time(results)
    assert isinstance(cycle_time, CycleTimeKpi)
    assert cycle_time.p50_s == pytest.approx(3.0)
    assert cycle_time.min_s == pytest.approx(1.0)
    assert cycle_time.max_s == pytest.approx(100.0)
    # The outlier must move p95 without moving p50.
    assert cycle_time.p95_s > cycle_time.p50_s


def test_report_always_declares_adoption_unmeasurable() -> None:
    results = _results([_case("a", predicted="submit", truth="submit")])
    report = compute_kpi_report(
        results,
        source_results_path="fake.json",
        split_name="fake",
    )
    names = [item.name for item in report.not_measured]
    assert "adoption" in names
    reason = next(
        item.reason for item in report.not_measured if item.name == "adoption"
    )
    assert "no users" in reason


def test_locked_split_report_matches_the_committed_eval_artifact() -> None:
    """The headline KPIs must agree with the eval harness they read from."""
    results = EvalResults.model_validate_json(
        LOCKED_RESULTS.read_text(encoding="utf-8")
    )
    report = compute_kpi_report(
        results,
        source_results_path=LOCKED_RESULTS.as_posix(),
        split_name="locked_test",
    )
    assert report.quality is not None
    assert report.quality.macro_f1 == results.classification.macro_f1
    assert report.cost is not None
    # The KPI layer reprices from raw token counts; it must land on the same
    # per-decision cost the eval harness recorded independently.
    assert report.cost.mean_usd_per_decision == pytest.approx(
        results.cost.mean_usd_per_case,
        abs=1e-6,
    )
    assert report.human_intervention is not None
    assert report.human_intervention.n_decisions == results.n_cases
    assert report.throughput is not None
    assert report.cycle_time is not None
    assert report.not_computed == []
