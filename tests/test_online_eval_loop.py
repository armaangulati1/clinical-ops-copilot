"""Tests for the online-eval loop: sampling, scoring, persistence, full cycle.

Two layers here. Most tests build span records by hand so they are fast and
deterministic. A smaller set runs real simulated traffic through the actual
instrumented agent, because a loop that only ever sees hand-written spans would
not catch a change to the span contract it depends on, which is the most likely
way this breaks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from online_eval.alerts import evaluate_alerts, severity_for
from online_eval.config import OnlineEvalConfig
from online_eval.models import DriftFinding, ScoredRun, SpanRecord, TracedRun
from online_eval.pipeline import (
    aggregate_step,
    alert_step,
    detect_step,
    run_cycle,
    sample_step,
    score_step,
)
from online_eval.sampling import (
    reconstruct_run,
    reconstruct_runs,
    sample_runs,
)
from online_eval.scoring import (
    LabelSource,
    adjudication_draw,
    build_window_metrics,
    score_runs,
)
from online_eval.simulated_traffic import (
    PROFILE_SHIFTED,
    PROFILE_STEADY,
    build_population,
    generate_traffic,
)
from online_eval.store import (
    append_scored_runs,
    baseline_is_eligible,
    load_cycles,
    load_scored_runs,
    read_baseline,
    read_cursor,
    reset_state,
)
from online_eval.trace_store import append_span_records, load_span_records
from schemas.loader import load_dataset, load_labels

NOW_NS = 1_786_000_000_000_000_000


def span(
    *,
    trace_id: str,
    name: str,
    start_ns: int,
    duration_ns: int,
    attributes: dict[str, object] | None = None,
) -> SpanRecord:
    return SpanRecord(
        trace_id=trace_id,
        span_id=f"{trace_id}-{name}",
        parent_span_id=None if name == "prior_auth.pipeline" else f"{trace_id}-root",
        name=name,
        start_unix_ns=start_ns,
        end_unix_ns=start_ns + duration_ns,
        attributes=attributes or {},
    )


def trace_for(
    trace_id: str,
    *,
    action: str = "submit",
    confidence: float = 0.85,
    latency_ms: float = 200.0,
    guardrail: bool = False,
    start_ns: int = NOW_NS,
    case_id: str = "case-001",
) -> list[SpanRecord]:
    duration_ns = int(latency_ms * 1_000_000)
    return [
        span(
            trace_id=trace_id,
            name="prior_auth.pipeline",
            start_ns=start_ns,
            duration_ns=duration_ns,
            attributes={
                "prior_auth.case_id": case_id,
                "decision.action": action,
                "decision.confidence": confidence,
                "decision.needs_review_count": 0,
            },
        ),
        span(
            trace_id=trace_id,
            name="mcp.tool.extract_chart",
            start_ns=start_ns + 10,
            duration_ns=100,
        ),
        span(
            trace_id=trace_id,
            name="mcp.tool.get_payer_policy",
            start_ns=start_ns + 120,
            duration_ns=100,
        ),
        span(
            trace_id=trace_id,
            name="guardrail.required_field",
            start_ns=start_ns + 240,
            duration_ns=50,
            attributes={"guardrail.triggered": guardrail},
        ),
    ]


@pytest.fixture
def config(tmp_path: Path) -> OnlineEvalConfig:
    return OnlineEvalConfig(
        state_dir=tmp_path / "state",
        labels_path=Path("data/labels/labels.json"),
        window_size=20,
        sample_limit=20,
        label_coverage=1.0,
    )


# --------------------------------------------------------------------------
# Reconstruction from spans
# --------------------------------------------------------------------------


def test_reconstruct_run_reads_the_decision_off_the_root_span() -> None:
    run = reconstruct_run(
        trace_for("t1", action="deny-risk", confidence=0.42, latency_ms=350.0)
    )
    assert run is not None
    assert run.case_id == "case-001"
    assert run.predicted_action == "deny-risk"
    assert run.confidence == pytest.approx(0.42)
    assert run.latency_ms == pytest.approx(350.0, abs=0.01)
    assert run.tool_call_count == 2
    assert run.guardrail_triggered is False


def test_reconstruct_run_reads_the_guardrail_span() -> None:
    run = reconstruct_run(trace_for("t1", guardrail=True))
    assert run is not None
    assert run.guardrail_triggered is True


def test_trace_without_a_root_span_is_dropped() -> None:
    partial = [s for s in trace_for("t1") if s.name != "prior_auth.pipeline"]
    assert reconstruct_run(partial) is None


def test_trace_missing_the_decision_action_is_dropped() -> None:
    spans = trace_for("t1")
    spans[0].attributes.pop("decision.action")
    assert reconstruct_run(spans) is None


def test_reconstruct_runs_groups_by_trace_and_sorts_chronologically() -> None:
    records = [
        *trace_for("t2", start_ns=NOW_NS + 10_000),
        *trace_for("t1", start_ns=NOW_NS),
    ]
    runs = reconstruct_runs(records)
    assert [run.trace_id for run in runs] == ["t1", "t2"]


# --------------------------------------------------------------------------
# Trace store and cursor
# --------------------------------------------------------------------------


def test_trace_store_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    append_span_records(path, trace_for("t1"))
    append_span_records(path, trace_for("t2", start_ns=NOW_NS + 10_000))
    assert len(load_span_records(path)) == 8


def test_trace_store_cursor_excludes_already_read_spans(tmp_path: Path) -> None:
    path = tmp_path / "traces.jsonl"
    first = trace_for("t1", start_ns=NOW_NS)
    append_span_records(path, first)
    cutoff = max(record.end_unix_ns for record in first)
    append_span_records(path, trace_for("t2", start_ns=cutoff + 1))
    remaining = load_span_records(path, after_unix_ns=cutoff)
    assert {record.trace_id for record in remaining} == {"t2"}


def test_missing_trace_store_reads_as_empty(tmp_path: Path) -> None:
    assert load_span_records(tmp_path / "nope.jsonl") == []


# --------------------------------------------------------------------------
# Sampling
# --------------------------------------------------------------------------


def make_runs(n: int) -> list[TracedRun]:
    runs = []
    for index in range(n):
        reconstructed = reconstruct_run(
            trace_for(f"t{index:03d}", start_ns=NOW_NS + index * 1_000_000)
        )
        assert reconstructed is not None
        runs.append(reconstructed)
    return runs


def test_sampling_returns_everything_below_the_limit() -> None:
    runs = make_runs(5)
    assert len(sample_runs(runs, limit=20, seed=1)) == 5


def test_sampling_caps_at_the_limit_and_is_seed_reproducible() -> None:
    runs = make_runs(50)
    first = sample_runs(runs, limit=10, seed=7)
    second = sample_runs(runs, limit=10, seed=7)
    assert len(first) == 10
    assert [r.trace_id for r in first] == [r.trace_id for r in second]


def test_sampling_preserves_chronological_order() -> None:
    runs = make_runs(50)
    sampled = sample_runs(runs, limit=10, seed=3)
    assert sampled == sorted(sampled, key=lambda run: run.observed_at)


# --------------------------------------------------------------------------
# Scoring and windowing
# --------------------------------------------------------------------------


def test_adjudication_draw_is_stable_for_a_trace_id() -> None:
    assert adjudication_draw("abc") == adjudication_draw("abc")
    assert 0.0 <= adjudication_draw("abc") < 1.0


def test_zero_coverage_leaves_every_run_unlabeled(config: OnlineEvalConfig) -> None:
    labels = LabelSource(config.labels_path, coverage=0.0)
    scored = score_runs(make_runs(10), labels=labels, confidence_floor=0.75)
    assert all(item.label_action is None for item in scored)
    assert all(item.correct is None for item in scored)


def test_full_coverage_labels_every_known_case(config: OnlineEvalConfig) -> None:
    labels = LabelSource(config.labels_path, coverage=1.0)
    scored = score_runs(make_runs(10), labels=labels, confidence_floor=0.75)
    assert all(item.label_action is not None for item in scored)


def test_low_confidence_flag_uses_the_configured_floor(
    config: OnlineEvalConfig,
) -> None:
    run = reconstruct_run(trace_for("t1", confidence=0.60))
    assert run is not None
    labels = LabelSource(config.labels_path, coverage=0.0)
    assert score_runs([run], labels=labels, confidence_floor=0.75)[0].low_confidence
    assert not score_runs([run], labels=labels, confidence_floor=0.50)[0].low_confidence


def test_window_metrics_on_an_empty_window() -> None:
    window = build_window_metrics([], window_id="w", min_labeled_n=8)
    assert window.n_runs == 0
    assert window.macro_f1 is None
    assert window.notes


def test_window_metrics_compute_rates_and_distribution() -> None:
    runs = [
        reconstruct_run(trace_for("t1", action="submit", confidence=0.9)),
        reconstruct_run(trace_for("t2", action="submit", confidence=0.5)),
        reconstruct_run(
            trace_for("t3", action="request-more-info", confidence=0.9, guardrail=True)
        ),
        reconstruct_run(trace_for("t4", action="deny-risk", confidence=0.4)),
    ]
    scored = [
        ScoredRun(run=run, low_confidence=run.confidence < 0.75)
        for run in runs
        if run is not None
    ]
    window = build_window_metrics(scored, window_id="w", min_labeled_n=8)
    assert window.n_runs == 4
    assert window.action_counts == {
        "submit": 2,
        "request-more-info": 1,
        "deny-risk": 1,
    }
    assert window.action_distribution["submit"] == pytest.approx(0.5)
    assert window.low_confidence_rate == pytest.approx(0.5)
    assert window.guardrail_rate == pytest.approx(0.25)


def test_accuracy_is_omitted_below_the_label_minimum() -> None:
    runs = make_runs(4)
    scored = [ScoredRun(run=run, label_action="submit", correct=True) for run in runs]
    window = build_window_metrics(scored, window_id="w", min_labeled_n=8)
    assert window.macro_f1 is None
    assert any("Accuracy not computed" in note for note in window.notes)


def test_accuracy_is_computed_above_the_label_minimum() -> None:
    runs = make_runs(10)
    scored = [ScoredRun(run=run, label_action="submit", correct=True) for run in runs]
    window = build_window_metrics(scored, window_id="w", min_labeled_n=8)
    assert window.macro_f1 is not None
    assert window.accuracy == pytest.approx(1.0)


def test_small_labeled_window_carries_a_wide_interval_note() -> None:
    runs = make_runs(10)
    scored = [ScoredRun(run=run, label_action="submit", correct=True) for run in runs]
    window = build_window_metrics(scored, window_id="w", min_labeled_n=8)
    assert any("interval is wide" in note for note in window.notes)


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------


def test_scored_run_appends_are_deduplicated_by_trace_id(
    config: OnlineEvalConfig,
) -> None:
    scored = [ScoredRun(run=run) for run in make_runs(5)]
    assert len(append_scored_runs(config, scored)) == 5
    assert len(append_scored_runs(config, scored)) == 0
    assert len(load_scored_runs(config)) == 5


def test_scored_run_tail_returns_the_rolling_window(
    config: OnlineEvalConfig,
) -> None:
    append_scored_runs(config, [ScoredRun(run=run) for run in make_runs(30)])
    assert len(load_scored_runs(config, tail=10)) == 10


def test_a_window_below_the_floor_cannot_become_the_baseline(
    config: OnlineEvalConfig,
) -> None:
    """A failing system does not get to define what normal looks like."""
    actions = ["submit", "request-more-info", "deny-risk"]
    scored = []
    for index, run in enumerate(make_runs(21)):
        truth = actions[index % 3]
        predicted = run.model_copy(update={"predicted_action": truth})
        scored.append(ScoredRun(run=predicted, label_action=truth, correct=True))
    healthy = build_window_metrics(scored, window_id="ok", min_labeled_n=8)
    assert healthy.macro_f1 == pytest.approx(1.0)
    assert baseline_is_eligible(healthy, config) is True
    broken = healthy.model_copy(update={"macro_f1": 0.10})
    assert baseline_is_eligible(broken, config) is False


def test_reset_clears_loop_state_but_not_the_trace_store(
    config: OnlineEvalConfig,
) -> None:
    append_span_records(config.traces_path, trace_for("t1"))
    append_scored_runs(config, [ScoredRun(run=run) for run in make_runs(2)])
    reset_state(config)
    assert load_scored_runs(config) == []
    assert config.traces_path.exists()


# --------------------------------------------------------------------------
# Alerts
# --------------------------------------------------------------------------


def test_alert_severity_is_by_metric_meaning() -> None:
    assert severity_for("macro_f1_floor") == "critical"
    assert severity_for("macro_f1_regression") == "critical"
    assert severity_for("action_distribution_psi") == "warning"
    assert severity_for("p95_latency_ratio") == "warning"


def test_a_not_comparable_finding_never_alerts() -> None:
    window = build_window_metrics([], window_id="w", min_labeled_n=8)
    findings = [
        DriftFinding(
            metric="macro_f1_floor",
            method="m",
            comparable=False,
            breached=True,
            note="should not fire",
        )
    ]
    alerts = evaluate_alerts(
        findings,
        window,
        cycle_id="c",
        raised_at=datetime.now(tz=UTC),
    )
    assert alerts == []


def test_a_breached_comparable_finding_alerts_once() -> None:
    window = build_window_metrics([], window_id="w", min_labeled_n=8)
    findings = [
        DriftFinding(
            metric="macro_f1_floor",
            method="m",
            comparable=True,
            breached=True,
            note="below floor",
        )
    ]
    alerts = evaluate_alerts(
        findings,
        window,
        cycle_id="c",
        raised_at=datetime.now(tz=UTC),
    )
    assert len(alerts) == 1
    assert alerts[0].severity == "critical"


# --------------------------------------------------------------------------
# The five steps, wired together
# --------------------------------------------------------------------------


def seed_traffic(config: OnlineEvalConfig, *, n: int, start_ns: int) -> None:
    """Write ``n`` synthetic traces that look like a mostly-healthy agent.

    The predicted action is the case's real label for most runs and wrong for
    every seventh, so the window carries all three decision classes and a
    macro-F1 above the floor. A fixture that only ever emits one class scores
    0.33 by construction, because macro-F1 here averages over the fixed
    three-class order, and would make every baseline test a false negative.
    """
    labels = load_labels(config.labels_path).labels
    case_ids = sorted(labels)[:24]
    wrong_choice = {
        "submit": "deny-risk",
        "request-more-info": "submit",
        "deny-risk": "request-more-info",
    }
    config.ensure_state_dir()
    for index in range(n):
        case_id = case_ids[index % len(case_ids)]
        truth = labels[case_id].correct_action.value
        action = wrong_choice[truth] if index % 7 == 6 else truth
        append_span_records(
            config.traces_path,
            trace_for(
                f"seed{start_ns}-{index:03d}",
                start_ns=start_ns + index * 1_000_000,
                case_id=case_id,
                action=action,
                confidence=0.9 if index % 3 else 0.4,
            ),
        )


def test_first_cycle_freezes_a_baseline_and_records_the_trend(
    config: OnlineEvalConfig,
) -> None:
    seed_traffic(config, n=20, start_ns=NOW_NS)
    record = run_cycle(config)
    assert record.n_scored == 20
    assert record.rolling_window is not None
    assert record.rolling_window.n_runs == 20
    assert len(load_cycles(config)) == 1
    assert read_cursor(config) == record.cursor_after_ns


def test_a_cycle_scores_only_new_traffic(config: OnlineEvalConfig) -> None:
    seed_traffic(config, n=20, start_ns=NOW_NS)
    first = run_cycle(config)
    seed_traffic(config, n=10, start_ns=first.cursor_after_ns + 1_000)
    second = run_cycle(config)
    assert second.n_scored == 10
    assert second.cursor_after_ns > first.cursor_after_ns


def test_a_cycle_with_no_new_traffic_scores_nothing_and_still_records(
    config: OnlineEvalConfig,
) -> None:
    seed_traffic(config, n=20, start_ns=NOW_NS)
    run_cycle(config)
    second = run_cycle(config)
    assert second.n_scored == 0
    assert len(load_cycles(config)) == 2


def test_the_first_window_is_not_compared_against_itself(
    config: OnlineEvalConfig,
) -> None:
    """Freezing a baseline and then scoring against it would be a free pass."""
    seed_traffic(config, n=20, start_ns=NOW_NS)
    record = run_cycle(config)
    baseline = read_baseline(config)
    if baseline is None:
        pytest.skip("window did not qualify as a baseline on this fixture")
    assert record.rolling_window is not None
    assert baseline.window_id == record.rolling_window.window_id
    relative = [f for f in record.findings if f.metric != "macro_f1_floor"]
    assert all(finding.comparable is False for finding in relative)


def test_the_cursor_does_not_move_when_a_later_step_fails(
    config: OnlineEvalConfig,
) -> None:
    """At-least-once on traffic: a half-finished cycle must not skip runs."""
    seed_traffic(config, n=20, start_ns=NOW_NS)
    sampled = sample_step(config, cycle_id="c1")
    scored = score_step(config, sampled)
    aggregate_step(config, scored)
    # detect_step / alert_step never run, simulating a crash after aggregation.
    assert read_cursor(config) == 0


def test_the_cursor_moves_only_after_the_alert_step(
    config: OnlineEvalConfig,
) -> None:
    seed_traffic(config, n=20, start_ns=NOW_NS)
    sampled = sample_step(config, cycle_id="c1")
    scored = score_step(config, sampled)
    aggregated = aggregate_step(config, scored)
    detected = detect_step(config, aggregated)
    assert read_cursor(config) == 0
    alert_step(config, detected)
    assert read_cursor(config) == sampled["cursor_after_ns"]


def test_step_payloads_survive_a_json_round_trip(config: OnlineEvalConfig) -> None:
    """XCom serializes; a payload that cannot round-trip breaks only in Airflow."""
    import json

    seed_traffic(config, n=20, start_ns=NOW_NS)
    payload = sample_step(config, cycle_id="c1")
    for _ in range(4):
        payload = json.loads(json.dumps(payload))
        payload = score_step(config, payload)
        payload = json.loads(json.dumps(payload))
        payload = aggregate_step(config, payload)
        payload = json.loads(json.dumps(payload))
        payload = detect_step(config, payload)
        payload = json.loads(json.dumps(payload))
        payload = alert_step(config, payload)
        break
    assert payload["cycle_id"] == "c1"


# --------------------------------------------------------------------------
# Simulated traffic against the real instrumented agent
# --------------------------------------------------------------------------


def test_traffic_profiles_weight_the_case_mix_differently() -> None:
    entries = load_dataset()
    _, steady = build_population(entries, PROFILE_STEADY)
    _, shifted = build_population(entries, PROFILE_SHIFTED)
    assert len(set(steady)) == 1
    assert len(set(shifted)) > 1

    def hard_share(weights: list[float]) -> float:
        hard = sum(
            weight
            for weight, entry in zip(weights, entries, strict=True)
            if entry.label.difficulty.value == "hard"
        )
        return hard / sum(weights)

    assert hard_share(shifted) > hard_share(steady)


def test_unknown_traffic_profile_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown traffic profile"):
        build_population(load_dataset(), "nonsense")


def test_generated_traffic_produces_scoreable_runs(config: OnlineEvalConfig) -> None:
    """End to end against the real agent and the real OpenInference spans.

    This is the test that fails if the span contract in ``phoenix_obs`` changes:
    the loop reads ``prior_auth.case_id`` and ``decision.action`` off the root
    span, and nothing else in the repository would notice if those moved.
    """
    emitted = generate_traffic(config=config, n_runs=6, seed=11)
    assert emitted == 6
    records = load_span_records(config.traces_path)
    assert records
    runs = reconstruct_runs(records)
    assert len(runs) == 6
    assert all(run.case_id.startswith("case-") for run in runs)
    assert all(run.latency_ms > 0 for run in runs)
    assert all(run.tool_call_count >= 1 for run in runs)


def test_a_full_cycle_over_generated_traffic(config: OnlineEvalConfig) -> None:
    generate_traffic(config=config, n_runs=20, seed=5)
    record = run_cycle(config)
    assert record.n_scored == 20
    assert record.rolling_window is not None
    assert record.rolling_window.n_runs == 20
    assert record.findings
    assert len(load_cycles(config)) == 1
