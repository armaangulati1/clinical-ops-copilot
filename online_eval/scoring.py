"""Score sampled runs and aggregate them into window metrics.

Deliberately thin. Every accuracy number here is produced by the repository's
existing metric code (``evals.metrics.classification``) and every percentile by
``evals.metrics.latency.percentile``. Reimplementing macro-F1 next to the
offline harness would create two accuracy definitions that could silently
diverge, which is the exact failure mode the KPI layer already avoids by reading
the harness output instead of recomputing it.

What is genuinely new here is what gets scored and when:

* **Ground truth is partial.** Production traffic is not labeled. Only an
  adjudicated subset carries a label, so ``macro_f1`` is computed on that subset
  and is ``None`` when the subset is too small.
* **The label-free signals carry the rest.** Action mix, low-confidence rate,
  guardrail rate and latency percentiles need no ground truth at all, so they
  cover the whole window. In a real deployment these are the signals that are
  available within minutes; accuracy arrives days later, if at all.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from evals.metrics.classification import (
    DECISION_CLASS_ORDER,
    compute_classification_metrics,
)
from evals.metrics.latency import percentile
from online_eval.config import OnlineEvalConfig
from online_eval.models import ScoredRun, TracedRun, WindowMetrics
from schemas.loader import load_labels

KNOWN_ACTIONS: tuple[str, ...] = tuple(action.value for action in DECISION_CLASS_ORDER)

_HASH_SPACE = 2**64

# Below this many adjudicated runs, the window carries an explicit wide-interval
# note alongside its accuracy so no reader treats one cycle's move as a result.
WIDE_INTERVAL_N = 20


def adjudication_draw(trace_id: str) -> float:
    """Stable pseudo-random draw in [0, 1) for one trace.

    Hash-based rather than RNG-based so a given run is either adjudicated or
    not, permanently, no matter how many times the loop replays it. A cycle that
    changed its mind about which runs are labeled would make the accuracy series
    non-reproducible.
    """
    digest = hashlib.sha256(trace_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / _HASH_SPACE


class LabelSource:
    """Ground truth for the adjudicated subset.

    In this repository the truth comes from the same held-out label file the
    offline harness uses, because the simulated traffic replays labeled
    synthetic cases. That is a property of the simulation, not of the design: in
    a deployment this class would read whatever the review queue adjudicated,
    and the rest of the loop would not change.

    The label file is read here and nowhere near the agent runtime, preserving
    the repository's existing rule that labels are eval-side only.
    """

    def __init__(self, labels_path: Path, *, coverage: float) -> None:
        self._labels = load_labels(labels_path)
        self._coverage = coverage

    def label_for(self, run: TracedRun) -> str | None:
        if self._coverage <= 0.0:
            return None
        if adjudication_draw(run.trace_id) >= self._coverage:
            return None
        label = self._labels.labels.get(run.case_id)
        if label is None:
            return None
        return label.correct_action.value


def score_runs(
    runs: list[TracedRun],
    *,
    labels: LabelSource,
    confidence_floor: float,
) -> list[ScoredRun]:
    """Attach scores to each run. Unlabeled runs keep ``correct=None``."""
    scored: list[ScoredRun] = []
    for run in runs:
        truth = labels.label_for(run)
        scored.append(
            ScoredRun(
                run=run,
                label_action=truth,
                correct=None if truth is None else run.predicted_action == truth,
                low_confidence=run.confidence < confidence_floor,
            )
        )
    return scored


def build_window_metrics(
    scored: list[ScoredRun],
    *,
    window_id: str,
    min_labeled_n: int,
    computed_at: datetime | None = None,
) -> WindowMetrics:
    """Aggregate scored runs into one window's metrics."""
    now = computed_at or datetime.now(tz=UTC)
    notes: list[str] = []
    if not scored:
        return WindowMetrics(
            window_id=window_id,
            computed_at=now,
            n_runs=0,
            n_labeled=0,
            notes=["Empty window: no runs were sampled."],
        )

    action_counts = dict.fromkeys(KNOWN_ACTIONS, 0)
    unknown_actions = 0
    for item in scored:
        action = item.run.predicted_action
        if action in action_counts:
            action_counts[action] += 1
        else:
            unknown_actions += 1
    if unknown_actions:
        notes.append(
            f"{unknown_actions} run(s) carried a decision action outside the "
            "known class set and are excluded from the action distribution."
        )

    total_classified = sum(action_counts.values())
    distribution = {
        action: (count / total_classified if total_classified else 0.0)
        for action, count in action_counts.items()
    }

    latencies = [item.run.latency_ms for item in scored]
    confidences = [item.run.confidence for item in scored]
    n_low_conf = sum(1 for item in scored if item.low_confidence)
    n_guardrail = sum(1 for item in scored if item.run.guardrail_triggered)

    labeled = [item for item in scored if item.is_labeled]
    macro_f1: float | None = None
    accuracy: float | None = None
    if len(labeled) < min_labeled_n:
        notes.append(
            f"Accuracy not computed: {len(labeled)} adjudicated run(s) in this "
            f"window, below the minimum of {min_labeled_n}. Unlabeled traffic "
            "is still covered by the distribution and rate metrics."
        )
    else:
        y_true = [item.label_action or "" for item in labeled]
        y_pred = [item.run.predicted_action for item in labeled]
        usable = [
            (truth, pred)
            for truth, pred in zip(y_true, y_pred, strict=True)
            if truth in KNOWN_ACTIONS and pred in KNOWN_ACTIONS
        ]
        if len(usable) < min_labeled_n:
            notes.append(
                "Accuracy not computed: too few adjudicated runs carried "
                "recognized decision classes."
            )
        else:
            metrics = compute_classification_metrics(
                [truth for truth, _ in usable],
                [pred for _, pred in usable],
            )
            macro_f1 = metrics.macro_f1
            accuracy = metrics.accuracy
            if len(usable) < WIDE_INTERVAL_N:
                notes.append(
                    f"macro-F1 computed on {len(usable)} adjudicated run(s). At "
                    "that size the interval is wide, so single-cycle movement "
                    "is indicative, not conclusive; the frozen-baseline "
                    "comparison is what the alert threshold is set against."
                )

    return WindowMetrics(
        window_id=window_id,
        computed_at=now,
        n_runs=len(scored),
        n_labeled=len(labeled),
        action_counts=action_counts,
        action_distribution={k: round(v, 6) for k, v in distribution.items()},
        mean_confidence=round(sum(confidences) / len(confidences), 6),
        low_confidence_rate=round(n_low_conf / len(scored), 6),
        guardrail_rate=round(n_guardrail / len(scored), 6),
        p50_latency_ms=round(percentile(latencies, 50), 3),
        p95_latency_ms=round(percentile(latencies, 95), 3),
        macro_f1=macro_f1,
        accuracy=accuracy,
        notes=notes,
    )


def build_label_source(config: OnlineEvalConfig) -> LabelSource:
    return LabelSource(config.labels_path, coverage=config.label_coverage)
