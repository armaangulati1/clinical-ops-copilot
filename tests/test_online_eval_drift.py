"""Unit tests for regression and drift detection.

Fixture-driven and fully deterministic: every window here is constructed
directly, so no agent runs and no traffic is generated. The detectors are the
part of the loop that decides whether someone gets woken up, so they are tested
on the states that actually matter: a real regression, a real population shift,
a quiet window, and the four ways a detector can be unable to check at all.
"""

from __future__ import annotations

from datetime import UTC, datetime

from online_eval.config import DriftThresholds
from online_eval.drift import (
    detect_drift,
    population_stability_index,
    psi_band,
)
from online_eval.models import DriftFinding, WindowMetrics

NOW = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)
THRESHOLDS = DriftThresholds()


def make_window(
    *,
    window_id: str = "w",
    n_runs: int = 60,
    n_labeled: int = 20,
    macro_f1: float | None = 0.80,
    low_confidence_rate: float = 0.10,
    guardrail_rate: float = 0.05,
    p95_latency_ms: float = 400.0,
    distribution: dict[str, float] | None = None,
) -> WindowMetrics:
    mix = distribution or {
        "submit": 0.5,
        "request-more-info": 0.3,
        "deny-risk": 0.2,
    }
    return WindowMetrics(
        window_id=window_id,
        computed_at=NOW,
        n_runs=n_runs,
        n_labeled=n_labeled,
        action_counts={key: int(value * n_runs) for key, value in mix.items()},
        action_distribution=mix,
        mean_confidence=0.85,
        low_confidence_rate=low_confidence_rate,
        guardrail_rate=guardrail_rate,
        p50_latency_ms=p95_latency_ms / 2,
        p95_latency_ms=p95_latency_ms,
        macro_f1=macro_f1,
        accuracy=macro_f1,
    )


def finding_for(findings: list[DriftFinding], metric: str) -> DriftFinding:
    for finding in findings:
        if finding.metric == metric:
            return finding
    raise AssertionError(f"no finding for metric {metric!r}")


# --------------------------------------------------------------------------
# PSI
# --------------------------------------------------------------------------


def test_psi_is_zero_for_identical_distributions() -> None:
    mix = {"submit": 0.5, "request-more-info": 0.3, "deny-risk": 0.2}
    assert population_stability_index(mix, mix) == 0.0


def test_psi_is_symmetric() -> None:
    a = {"submit": 0.5, "request-more-info": 0.3, "deny-risk": 0.2}
    b = {"submit": 0.2, "request-more-info": 0.5, "deny-risk": 0.3}
    forward = population_stability_index(a, b)
    backward = population_stability_index(b, a)
    assert abs(forward - backward) < 1e-12


def test_psi_grows_with_the_size_of_the_shift() -> None:
    base = {"submit": 0.5, "request-more-info": 0.3, "deny-risk": 0.2}
    small = {"submit": 0.45, "request-more-info": 0.33, "deny-risk": 0.22}
    large = {"submit": 0.1, "request-more-info": 0.2, "deny-risk": 0.7}
    assert population_stability_index(base, small) < population_stability_index(
        base, large
    )


def test_psi_handles_a_class_that_disappeared() -> None:
    """A class dropping to zero must give a large finite number, not inf.

    The agent silently ceasing to emit a decision class is one of the loudest
    real signals there is, so it has to survive the arithmetic.
    """
    base = {"submit": 0.5, "request-more-info": 0.3, "deny-risk": 0.2}
    collapsed = {"submit": 0.7, "request-more-info": 0.3, "deny-risk": 0.0}
    value = population_stability_index(base, collapsed)
    assert value > THRESHOLDS.action_distribution_psi
    assert value != float("inf")


def test_psi_handles_a_class_that_appeared() -> None:
    base = {"submit": 0.8, "request-more-info": 0.2, "deny-risk": 0.0}
    widened = {"submit": 0.4, "request-more-info": 0.2, "deny-risk": 0.4}
    assert population_stability_index(base, widened) > 0.25


def test_psi_bands() -> None:
    assert psi_band(0.05) == "stable"
    assert psi_band(0.15) == "moderate shift"
    assert psi_band(0.40) == "major shift"


# --------------------------------------------------------------------------
# Regression detectors
# --------------------------------------------------------------------------


def test_quiet_window_breaches_nothing() -> None:
    baseline = make_window(window_id="baseline")
    current = make_window(window_id="current")
    findings = detect_drift(current, baseline, THRESHOLDS)
    assert all(finding.comparable for finding in findings)
    assert not any(finding.breached for finding in findings)


def test_macro_f1_regression_breaches_past_the_threshold() -> None:
    baseline = make_window(window_id="baseline", macro_f1=0.80)
    current = make_window(window_id="current", macro_f1=0.65)
    finding = finding_for(
        detect_drift(current, baseline, THRESHOLDS), "macro_f1_regression"
    )
    assert finding.comparable is True
    assert finding.breached is True
    assert finding.delta is not None
    assert abs(finding.delta - (-0.15)) < 1e-9


def test_macro_f1_regression_just_under_the_threshold_does_not_breach() -> None:
    baseline = make_window(window_id="baseline", macro_f1=0.80)
    current = make_window(window_id="current", macro_f1=0.705)
    finding = finding_for(
        detect_drift(current, baseline, THRESHOLDS), "macro_f1_regression"
    )
    assert finding.comparable is True
    assert finding.breached is False


def test_macro_f1_improvement_never_breaches() -> None:
    baseline = make_window(window_id="baseline", macro_f1=0.60)
    current = make_window(window_id="current", macro_f1=0.90)
    finding = finding_for(
        detect_drift(current, baseline, THRESHOLDS), "macro_f1_regression"
    )
    assert finding.breached is False


def test_floor_catches_a_slide_the_step_delta_misses() -> None:
    """A drift small enough to pass the delta check but below the floor.

    This is the case the floor exists for: quality that walks down in
    increments smaller than the alerting delta.
    """
    baseline = make_window(window_id="baseline", macro_f1=0.52)
    current = make_window(window_id="current", macro_f1=0.45)
    findings = detect_drift(current, baseline, THRESHOLDS)
    assert finding_for(findings, "macro_f1_regression").breached is False
    assert finding_for(findings, "macro_f1_floor").breached is True


def test_low_confidence_and_guardrail_rate_rises() -> None:
    baseline = make_window(
        window_id="baseline",
        low_confidence_rate=0.10,
        guardrail_rate=0.05,
    )
    current = make_window(
        window_id="current",
        low_confidence_rate=0.30,
        guardrail_rate=0.40,
    )
    findings = detect_drift(current, baseline, THRESHOLDS)
    assert finding_for(findings, "low_confidence_rate_rise").breached is True
    assert finding_for(findings, "guardrail_rate_rise").breached is True


def test_rate_falling_is_not_a_breach() -> None:
    baseline = make_window(window_id="baseline", low_confidence_rate=0.40)
    current = make_window(window_id="current", low_confidence_rate=0.05)
    finding = finding_for(
        detect_drift(current, baseline, THRESHOLDS), "low_confidence_rate_rise"
    )
    assert finding.breached is False


def test_action_distribution_psi_breaches_on_a_major_shift() -> None:
    baseline = make_window(
        window_id="baseline",
        distribution={"submit": 0.6, "request-more-info": 0.3, "deny-risk": 0.1},
    )
    current = make_window(
        window_id="current",
        distribution={"submit": 0.1, "request-more-info": 0.3, "deny-risk": 0.6},
    )
    finding = finding_for(
        detect_drift(current, baseline, THRESHOLDS), "action_distribution_psi"
    )
    assert finding.breached is True


def test_drift_can_fire_while_accuracy_is_unchanged() -> None:
    """The reason PSI is here at all.

    Population shift with identical macro-F1: a label-only monitor sees nothing,
    and the loop still notices that the traffic changed.
    """
    baseline = make_window(
        window_id="baseline",
        macro_f1=0.80,
        distribution={"submit": 0.7, "request-more-info": 0.2, "deny-risk": 0.1},
    )
    current = make_window(
        window_id="current",
        macro_f1=0.80,
        distribution={"submit": 0.1, "request-more-info": 0.2, "deny-risk": 0.7},
    )
    findings = detect_drift(current, baseline, THRESHOLDS)
    assert finding_for(findings, "macro_f1_regression").breached is False
    assert finding_for(findings, "action_distribution_psi").breached is True


# --------------------------------------------------------------------------
# Latency, including the absolute floor
# --------------------------------------------------------------------------


def test_latency_ratio_breaches_above_the_absolute_floor() -> None:
    baseline = make_window(window_id="baseline", p95_latency_ms=400.0)
    current = make_window(window_id="current", p95_latency_ms=1200.0)
    finding = finding_for(
        detect_drift(current, baseline, THRESHOLDS), "p95_latency_ratio"
    )
    assert finding.comparable is True
    assert finding.breached is True


def test_latency_ratio_is_not_evaluated_below_the_absolute_floor() -> None:
    """Regression test for a real false positive this loop produced.

    The first end-to-end run reported a '2.95x latency regression' that was
    0.9ms -> 2.7ms of scheduler jitter. A ratio with no absolute floor alerts on
    noise, so below the floor the detector reports itself as not comparable
    rather than green or red.
    """
    baseline = make_window(window_id="baseline", p95_latency_ms=0.9)
    current = make_window(window_id="current", p95_latency_ms=2.7)
    finding = finding_for(
        detect_drift(current, baseline, THRESHOLDS), "p95_latency_ratio"
    )
    assert finding.comparable is False
    assert finding.breached is False
    assert "floor" in finding.note


# --------------------------------------------------------------------------
# "Could not check" is not "checked and fine"
# --------------------------------------------------------------------------


def test_thin_window_reports_every_detector_as_not_comparable() -> None:
    current = make_window(window_id="current", n_runs=3, n_labeled=2)
    findings = detect_drift(current, make_window(window_id="baseline"), THRESHOLDS)
    assert len(findings) == 6
    assert all(finding.comparable is False for finding in findings)
    assert all(finding.breached is False for finding in findings)


def test_no_baseline_still_evaluates_the_absolute_floor() -> None:
    """Without a baseline the relative checks cannot run, but the floor can."""
    current = make_window(window_id="current", macro_f1=0.20)
    findings = detect_drift(current, None, THRESHOLDS)
    floor = finding_for(findings, "macro_f1_floor")
    assert floor.comparable is True
    assert floor.breached is True
    relative = [f for f in findings if f.metric != "macro_f1_floor"]
    assert all(finding.comparable is False for finding in relative)


def test_missing_labels_make_the_accuracy_detectors_not_comparable() -> None:
    baseline = make_window(window_id="baseline", macro_f1=0.80)
    current = make_window(window_id="current", macro_f1=None, n_labeled=1)
    findings = detect_drift(current, baseline, THRESHOLDS)
    assert finding_for(findings, "macro_f1_regression").comparable is False
    assert finding_for(findings, "macro_f1_floor").comparable is False
    # Label-free detectors still run on the same window.
    assert finding_for(findings, "action_distribution_psi").comparable is True
    assert finding_for(findings, "low_confidence_rate_rise").comparable is True


def test_every_detector_reports_exactly_once_per_call() -> None:
    findings = detect_drift(
        make_window(window_id="current"),
        make_window(window_id="baseline"),
        THRESHOLDS,
    )
    metrics = [finding.metric for finding in findings]
    assert len(metrics) == len(set(metrics)) == 6


def test_every_finding_records_its_method() -> None:
    findings = detect_drift(
        make_window(window_id="current"),
        make_window(window_id="baseline"),
        THRESHOLDS,
    )
    assert all(finding.method.strip() for finding in findings)
