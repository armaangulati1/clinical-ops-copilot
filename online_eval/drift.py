"""Regression and drift detection against a frozen baseline window.

Two different questions, deliberately kept apart:

* **Regression** -- did a metric get worse than it was? Absolute deltas against
  the baseline window, plus one hard floor on macro-F1 so a slow slide that
  never trips a single-step delta still gets caught.
* **Drift** -- did the *input population* change, whether or not quality moved?
  Population Stability Index on the decision-action mix. PSI needs no ground
  truth, so it fires on the unlabeled majority of traffic, which is the part a
  label-dependent metric cannot see.

Three properties this module is built around, each of which is a way monitors
go wrong in practice:

1. **"Could not check" is not "checked and fine."** Every detector returns a
   finding with ``comparable=False`` when it lacked a baseline, lacked labels or
   lacked volume. A detector that returned ``breached=False`` in those states
   would report a green board while looking at nothing.
2. **Small windows do not alert.** Below ``min_window_n`` runs the findings are
   emitted but marked not comparable, because a two-run window can move a rate
   by 0.5 and mean nothing.
3. **The method travels with the number.** Each finding names how it was
   computed, so a reader is never left to assume that a conventional threshold
   is a statistical result.
"""

from __future__ import annotations

import math

from online_eval.config import DriftThresholds
from online_eval.models import DriftFinding, WindowMetrics

PSI_EPSILON = 1e-6

# Conventional PSI interpretation bands. These are industry rules of thumb, not
# a hypothesis test, and are recorded on the finding as such.
PSI_BAND_INVESTIGATE = 0.10
PSI_BAND_ACT = 0.25


def population_stability_index(
    baseline: dict[str, float],
    current: dict[str, float],
    *,
    epsilon: float = PSI_EPSILON,
) -> float:
    """PSI between two categorical distributions over the same key space.

    ``sum((current - baseline) * ln(current / baseline))`` over the union of
    keys, with both proportions floored at ``epsilon`` so an empty bucket gives
    a large-but-finite contribution instead of a division by zero or an
    infinity. A zero-count bucket is a real and common signal (the agent stopped
    emitting a class), so it must produce a number the caller can threshold,
    not a crash.
    """
    keys = sorted(set(baseline) | set(current))
    total = 0.0
    for key in keys:
        base_p = max(baseline.get(key, 0.0), epsilon)
        curr_p = max(current.get(key, 0.0), epsilon)
        total += (curr_p - base_p) * math.log(curr_p / base_p)
    return total


def psi_band(value: float) -> str:
    if value < PSI_BAND_INVESTIGATE:
        return "stable"
    if value < PSI_BAND_ACT:
        return "moderate shift"
    return "major shift"


def _not_comparable(metric: str, method: str, note: str) -> DriftFinding:
    return DriftFinding(
        metric=metric,
        method=method,
        comparable=False,
        breached=False,
        note=note,
    )


def _check_macro_f1_regression(
    current: WindowMetrics,
    baseline: WindowMetrics,
    thresholds: DriftThresholds,
) -> DriftFinding:
    method = (
        "Absolute drop in macro-F1 on the adjudicated subset, current rolling "
        "window minus baseline window, computed by "
        "evals.metrics.classification.compute_classification_metrics."
    )
    if baseline.macro_f1 is None or current.macro_f1 is None:
        return _not_comparable(
            "macro_f1_regression",
            method,
            (
                "No macro-F1 on one side of the comparison: baseline labeled "
                f"n={baseline.n_labeled}, current labeled n={current.n_labeled}, "
                f"minimum {thresholds.min_labeled_n}."
            ),
        )
    delta = current.macro_f1 - baseline.macro_f1
    return DriftFinding(
        metric="macro_f1_regression",
        method=method,
        comparable=True,
        breached=delta <= -thresholds.macro_f1_abs_drop,
        baseline_value=round(baseline.macro_f1, 6),
        current_value=round(current.macro_f1, 6),
        delta=round(delta, 6),
        threshold=-thresholds.macro_f1_abs_drop,
        note=(
            f"macro-F1 moved {delta:+.4f} against a baseline of "
            f"{baseline.macro_f1:.4f} on {current.n_labeled} adjudicated run(s)."
        ),
    )


def _check_macro_f1_floor(
    current: WindowMetrics,
    thresholds: DriftThresholds,
) -> DriftFinding:
    method = (
        "Hard floor on rolling macro-F1, independent of the baseline. Catches a "
        "slow slide that never trips the single-step delta."
    )
    if current.macro_f1 is None:
        return _not_comparable(
            "macro_f1_floor",
            method,
            (
                f"No macro-F1 in the current window ({current.n_labeled} "
                f"adjudicated run(s), minimum {thresholds.min_labeled_n})."
            ),
        )
    return DriftFinding(
        metric="macro_f1_floor",
        method=method,
        comparable=True,
        breached=current.macro_f1 < thresholds.macro_f1_floor,
        current_value=round(current.macro_f1, 6),
        threshold=thresholds.macro_f1_floor,
        note=(
            f"Rolling macro-F1 {current.macro_f1:.4f} against a floor of "
            f"{thresholds.macro_f1_floor:.2f}."
        ),
    )


def _check_rate_rise(
    *,
    metric: str,
    method: str,
    baseline_value: float,
    current_value: float,
    threshold: float,
) -> DriftFinding:
    delta = current_value - baseline_value
    return DriftFinding(
        metric=metric,
        method=method,
        comparable=True,
        breached=delta >= threshold,
        baseline_value=round(baseline_value, 6),
        current_value=round(current_value, 6),
        delta=round(delta, 6),
        threshold=threshold,
        note=(f"Rate moved {delta:+.4f} against a baseline of {baseline_value:.4f}."),
    )


def _check_latency(
    current: WindowMetrics,
    baseline: WindowMetrics,
    thresholds: DriftThresholds,
) -> DriftFinding:
    method = (
        "Ratio of rolling p95 end-to-end latency to baseline p95, percentiles "
        "from evals.metrics.latency.percentile."
    )
    if baseline.p95_latency_ms <= 0.0:
        return _not_comparable(
            "p95_latency_ratio",
            method,
            "Baseline window recorded no positive p95 latency to divide by.",
        )
    if baseline.p95_latency_ms < thresholds.p95_latency_floor_ms:
        return _not_comparable(
            "p95_latency_ratio",
            method,
            (
                f"Baseline p95 is {baseline.p95_latency_ms:.2f}ms, below the "
                f"{thresholds.p95_latency_floor_ms:.0f}ms floor for evaluating a "
                "ratio. At that scale the ratio tracks scheduler jitter rather "
                "than the agent, so it is reported and not alerted on."
            ),
        )
    ratio = current.p95_latency_ms / baseline.p95_latency_ms
    return DriftFinding(
        metric="p95_latency_ratio",
        method=method,
        comparable=True,
        breached=ratio >= thresholds.p95_latency_ratio,
        baseline_value=round(baseline.p95_latency_ms, 3),
        current_value=round(current.p95_latency_ms, 3),
        delta=round(ratio, 4),
        threshold=thresholds.p95_latency_ratio,
        note=(
            f"p95 latency is {ratio:.2f}x the baseline "
            f"({current.p95_latency_ms:.1f}ms vs {baseline.p95_latency_ms:.1f}ms)."
        ),
    )


def _check_action_psi(
    current: WindowMetrics,
    baseline: WindowMetrics,
    thresholds: DriftThresholds,
) -> DriftFinding:
    method = (
        "Population Stability Index over the decision-action mix. Needs no "
        "ground truth, so it covers unlabeled traffic. The 0.10/0.25 bands are "
        "the conventional rules of thumb, not a hypothesis test."
    )
    if not baseline.action_distribution or not current.action_distribution:
        return _not_comparable(
            "action_distribution_psi",
            method,
            "One side of the comparison has no action distribution.",
        )
    value = population_stability_index(
        baseline.action_distribution,
        current.action_distribution,
    )
    return DriftFinding(
        metric="action_distribution_psi",
        method=method,
        comparable=True,
        breached=value >= thresholds.action_distribution_psi,
        current_value=round(value, 6),
        threshold=thresholds.action_distribution_psi,
        note=(
            f"PSI {value:.4f} ({psi_band(value)}). Baseline mix "
            f"{baseline.action_counts} vs current mix {current.action_counts}."
        ),
    )


def detect_drift(
    current: WindowMetrics,
    baseline: WindowMetrics | None,
    thresholds: DriftThresholds,
) -> list[DriftFinding]:
    """Run every detector against the current window.

    Always returns one finding per detector, comparable or not, so the caller
    can tell an all-clear from an unchecked board.
    """
    findings: list[DriftFinding] = []
    metrics_checked = (
        "macro_f1_regression",
        "macro_f1_floor",
        "low_confidence_rate_rise",
        "guardrail_rate_rise",
        "p95_latency_ratio",
        "action_distribution_psi",
    )

    if current.n_runs < thresholds.min_window_n:
        note = (
            f"Window holds {current.n_runs} run(s), below the minimum of "
            f"{thresholds.min_window_n}. Metrics are recorded but no detector "
            "is allowed to alert on them."
        )
        return [
            _not_comparable(metric, "Insufficient window volume.", note)
            for metric in metrics_checked
        ]

    if baseline is None:
        note = (
            "No baseline window has been frozen yet, so nothing can be compared "
            "against it. The first window that clears the volume and label "
            "minimums becomes the baseline."
        )
        findings.append(_check_macro_f1_floor(current, thresholds))
        findings.extend(
            _not_comparable(metric, "No baseline window.", note)
            for metric in metrics_checked
            if metric != "macro_f1_floor"
        )
        return findings

    findings.append(_check_macro_f1_regression(current, baseline, thresholds))
    findings.append(_check_macro_f1_floor(current, thresholds))
    findings.append(
        _check_rate_rise(
            metric="low_confidence_rate_rise",
            method=(
                "Absolute rise in the share of decisions below the configured "
                "planner-confidence floor. Label-free, so it covers the whole "
                "window rather than the adjudicated subset."
            ),
            baseline_value=baseline.low_confidence_rate,
            current_value=current.low_confidence_rate,
            threshold=thresholds.low_confidence_rate_abs_rise,
        )
    )
    findings.append(
        _check_rate_rise(
            metric="guardrail_rate_rise",
            method=(
                "Absolute rise in the share of runs where the deterministic "
                "required-field guardrail rewrote the decision."
            ),
            baseline_value=baseline.guardrail_rate,
            current_value=current.guardrail_rate,
            threshold=thresholds.guardrail_rate_abs_rise,
        )
    )
    findings.append(_check_latency(current, baseline, thresholds))
    findings.append(_check_action_psi(current, baseline, thresholds))
    return findings
