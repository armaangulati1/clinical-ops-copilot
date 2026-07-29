"""Compute the operational KPIs from a recorded evaluation run.

The inputs are the artifacts the eval harness already writes. Nothing here
calls a model, so the harness runs offline and is safe in CI.
"""

from __future__ import annotations

from evals.metrics.latency import percentile
from evals.models import CaseEvalResult, EvalResults
from kpi.models import (
    CostKpi,
    CycleTimeKpi,
    HumanInterventionKpi,
    KpiReport,
    KpiScope,
    QualityKpi,
    ThroughputKpi,
    UnmeasuredKpi,
)
from schemas.run_metrics import (
    INPUT_COST_PER_TOKEN_USD,
    OUTPUT_COST_PER_TOKEN_USD,
    estimate_planner_cost_usd,
)

MS_PER_SECOND = 1000.0
SECONDS_PER_MINUTE = 60.0
SECONDS_PER_HOUR = 3600.0

ADOPTION_REASON = (
    "Adoption has no denominator here. This repository is a demo on synthetic "
    "cases with no users, no seats, and no deployed workflow, so any adoption "
    "figure would be invented. It is measurable only against a real user base."
)


def _wall_clock_ms(case_results: list[CaseEvalResult]) -> list[float]:
    """Per-decision end-to-end wall clock, dropping unrecorded zeros."""
    return [
        result.total_latency_ms
        for result in case_results
        if result.total_latency_ms > 0
    ]


def compute_throughput(results: EvalResults) -> ThroughputKpi | UnmeasuredKpi:
    latencies_ms = _wall_clock_ms(results.case_results)
    if not latencies_ms:
        return UnmeasuredKpi(
            name="throughput",
            reason=(
                "No per-decision wall clock was recorded in this run "
                "(total_latency_ms is zero for every case)."
            ),
        )
    total_s = sum(latencies_ms) / MS_PER_SECOND
    n = len(latencies_ms)
    return ThroughputKpi(
        n_decisions=n,
        total_wall_clock_s=round(total_s, 3),
        decisions_per_minute=round(n / total_s * SECONDS_PER_MINUTE, 4),
        decisions_per_hour=round(n / total_s * SECONDS_PER_HOUR, 2),
        concurrency=1,
        method=(
            "Decisions divided by the summed per-decision wall clock of the "
            "recorded run. The harness executes cases one at a time, so this "
            "is serial throughput on one machine, not a capacity figure."
        ),
    )


def compute_quality(
    results: EvalResults,
    *,
    source_results_path: str,
) -> QualityKpi | UnmeasuredKpi:
    classification = results.classification
    if classification.n_cases == 0:
        return UnmeasuredKpi(
            name="quality",
            reason="The recorded run contains no classified decisions.",
        )
    return QualityKpi(
        macro_f1=classification.macro_f1,
        accuracy=classification.accuracy,
        n_decisions=classification.n_cases,
        per_class_f1={
            label: metrics.f1 for label, metrics in classification.per_class.items()
        },
        source=f"{source_results_path} (classification block)",
        method=(
            "Read directly from the eval harness output. This KPI is bound to "
            "the existing macro-F1 on the locked held-out split and is not "
            "recomputed here, so the KPI layer cannot drift from the eval "
            "layer or introduce a second accuracy number."
        ),
    )


def compute_cost(results: EvalResults) -> CostKpi | UnmeasuredKpi:
    with_usage = [
        result for result in results.case_results if result.planner_metrics is not None
    ]
    if not with_usage:
        return UnmeasuredKpi(
            name="cost",
            reason=(
                "No planner token usage was recorded in this run. The offline "
                "stub planner issues no model calls, so it has no token cost "
                "to report."
            ),
        )
    total_input = 0
    total_output = 0
    for result in with_usage:
        metrics = result.planner_metrics
        assert metrics is not None
        total_input += metrics.usage.input_tokens
        total_output += metrics.usage.output_tokens
    if total_input + total_output == 0:
        return UnmeasuredKpi(
            name="cost",
            reason=(
                "Every recorded decision reports zero tokens. The offline "
                "stub planner issues no model calls, so this run has no token "
                "cost. Reporting $0.00 per decision here would read as a "
                "measurement when it is an absence of one."
            ),
        )
    n = len(with_usage)
    total_usd = estimate_planner_cost_usd(
        input_tokens=total_input,
        output_tokens=total_output,
    )
    mean_usd = total_usd / n
    return CostKpi(
        n_decisions_with_usage=n,
        total_input_tokens=total_input,
        total_output_tokens=total_output,
        mean_tokens_per_decision=round((total_input + total_output) / n, 2),
        mean_usd_per_decision=round(mean_usd, 6),
        total_usd=round(total_usd, 6),
        projected_usd_per_1000_decisions=round(mean_usd * 1000, 4),
        pricing_basis=(
            f"${INPUT_COST_PER_TOKEN_USD * 1_000_000:.2f} per million input "
            f"tokens and ${OUTPUT_COST_PER_TOKEN_USD * 1_000_000:.2f} per "
            "million output tokens, from schemas/run_metrics.py list pricing."
        ),
        method=(
            "Summed from the token counts the planner recorded on each "
            "decision, then priced with the repository's own cost helper. "
            "The per-1000 figure is arithmetic on the measured mean, not an "
            "observation at that volume."
        ),
    )


def compute_human_intervention(
    results: EvalResults,
) -> HumanInterventionKpi | UnmeasuredKpi:
    missing = [
        result.case_id
        for result in results.case_results
        if result.approval_required is None or result.guardrail_triggered is None
    ]
    if missing:
        return UnmeasuredKpi(
            name="human_intervention_rate",
            reason=(
                "The recorded run did not capture approval-gate and guardrail "
                f"outcomes for {len(missing)} of {len(results.case_results)} "
                "decisions. Re-run the eval harness, or backfill the run from "
                "its run log, before reading this KPI."
            ),
        )
    if not results.case_results:
        return UnmeasuredKpi(
            name="human_intervention_rate",
            reason="The recorded run contains no decisions.",
        )
    n_approval = 0
    n_guardrail = 0
    n_both = 0
    n_intervened = 0
    for result in results.case_results:
        approval = bool(result.approval_required)
        guardrail = bool(result.guardrail_triggered)
        n_approval += approval
        n_guardrail += guardrail
        n_both += approval and guardrail
        n_intervened += approval or guardrail
    n = len(results.case_results)
    return HumanInterventionKpi(
        n_decisions=n,
        n_intervened=n_intervened,
        rate=round(n_intervened / n, 4),
        n_approval_gate=n_approval,
        n_guardrail=n_guardrail,
        n_both=n_both,
        definition=(
            "A decision counts as intervened when the approval policy "
            "(agent.approval_policy.requires_approval) requires a human to "
            "release it, or when the deterministic missing-field guardrail "
            "rewrites it (agent.decision_guardrail). The two overlap, so the "
            "rate is the union, not the sum. This offline eval run executed no "
            "gate and no human reviewed any decision, so the rate is a "
            "property of the decisions and the policy, not a record of reviews "
            "that took place."
        ),
        method=(
            "Evaluated per decision against the same approval policy the "
            "runtime uses. The rate is driven mostly by policy design rather "
            "than model behaviour: the policy would send every submit and every "
            "deny-risk decision to a human by construction, so a high rate "
            "here is the safety posture working, not the agent failing."
        ),
    )


def compute_cycle_time(results: EvalResults) -> CycleTimeKpi | UnmeasuredKpi:
    latencies_ms = _wall_clock_ms(results.case_results)
    if not latencies_ms:
        return UnmeasuredKpi(
            name="cycle_time",
            reason=(
                "No per-decision wall clock was recorded in this run "
                "(total_latency_ms is zero for every case)."
            ),
        )
    return CycleTimeKpi(
        n_decisions=len(latencies_ms),
        p50_s=round(percentile(latencies_ms, 50) / MS_PER_SECOND, 3),
        p95_s=round(percentile(latencies_ms, 95) / MS_PER_SECOND, 3),
        mean_s=round(sum(latencies_ms) / len(latencies_ms) / MS_PER_SECOND, 3),
        min_s=round(min(latencies_ms) / MS_PER_SECOND, 3),
        max_s=round(max(latencies_ms) / MS_PER_SECOND, 3),
        method=(
            "End-to-end wall clock per decision, covering MCP tool calls, "
            "planning, and guardrail enforcement. This is wider than the "
            "harness's existing latency block, which times the planner call "
            "alone. Percentiles at this N are indicative only."
        ),
    )


def _scope_caveats(results: EvalResults) -> list[str]:
    caveats = [
        "Synthetic cases with human-confirmed labels. No patient data.",
        (
            f"N is {results.n_cases} decisions. Every rate and percentile "
            "below carries a wide interval at this size."
        ),
        (
            "One sequential run on one developer machine. Timing figures "
            "include no concurrency, no queueing, and no warm-up control."
        ),
        (
            "Cost is planner tokens only. Infrastructure, retries outside the "
            "recorded run, and human review time are not priced."
        ),
    ]
    if results.judge_validation_n == 0:
        caveats.append(
            "No LLM-as-judge score is part of any KPI here. This run carries "
            "no judge validation, and in this repository the judge failed its "
            "agreement checks against human ratings and is excluded from "
            "scoring."
        )
    return caveats


def compute_kpi_report(
    results: EvalResults,
    *,
    source_results_path: str,
    split_name: str,
) -> KpiReport:
    """Build the full KPI report for one recorded evaluation run."""
    scope = KpiScope(
        source_results_path=source_results_path,
        split_name=split_name,
        n_decisions=results.n_cases,
        planner_model=results.planner_model,
        caveats=_scope_caveats(results),
    )
    report = KpiReport(scope=scope)
    report.not_measured.append(UnmeasuredKpi(name="adoption", reason=ADOPTION_REASON))

    throughput = compute_throughput(results)
    if isinstance(throughput, ThroughputKpi):
        report.throughput = throughput
    else:
        report.not_computed.append(throughput)

    quality = compute_quality(results, source_results_path=source_results_path)
    if isinstance(quality, QualityKpi):
        report.quality = quality
    else:
        report.not_computed.append(quality)

    cost = compute_cost(results)
    if isinstance(cost, CostKpi):
        report.cost = cost
    else:
        report.not_computed.append(cost)

    intervention = compute_human_intervention(results)
    if isinstance(intervention, HumanInterventionKpi):
        report.human_intervention = intervention
    else:
        report.not_computed.append(intervention)

    cycle_time = compute_cycle_time(results)
    if isinstance(cycle_time, CycleTimeKpi):
        report.cycle_time = cycle_time
    else:
        report.not_computed.append(cycle_time)

    return report
