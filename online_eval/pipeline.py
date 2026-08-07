"""The five steps of one online-eval cycle: sample, score, aggregate, detect, alert.

Each step takes and returns JSON-serializable dicts. That shape is not
decoration: it is what lets the same functions run as five separate Airflow
tasks passing payloads through XCom, and as one in-process call from the CLI,
with no second implementation. The DAG in ``orchestration/dags/`` contains no
evaluation logic at all; it only wires these five functions together, which is
what keeps the loop testable without an orchestrator.

Two ordering properties worth knowing before changing anything here:

* **The cursor advances last.** ``sample_step`` reads the high-water mark but
  does not move it; ``alert_step`` writes it after the cycle record is
  persisted. A cycle that dies at the scoring step therefore re-reads the same
  traffic next time rather than skipping it. That makes the loop at-least-once
  on traffic, which is the safe direction: re-scoring a run is harmless, never
  scoring it is a blind spot.
* **Appends are deduplicated by trace id**, so an orchestrator retry cannot
  double-count a run into the rolling window.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from online_eval.alerts import evaluate_alerts, format_alert_summary
from online_eval.config import OnlineEvalConfig
from online_eval.drift import detect_drift
from online_eval.models import (
    AlertEvent,
    CycleRecord,
    DriftFinding,
    ScoredRun,
    TracedRun,
    WindowMetrics,
)
from online_eval.sampling import load_runs_from_store, sample_runs
from online_eval.scoring import build_label_source, build_window_metrics, score_runs
from online_eval.store import (
    append_alerts,
    append_cycle,
    append_scored_runs,
    load_scored_runs,
    maybe_promote_baseline,
    read_baseline,
    read_cursor,
    write_cursor,
)


def new_cycle_id(now: datetime | None = None) -> str:
    stamp = (now or datetime.now(tz=UTC)).strftime("%Y%m%dT%H%M%S%f")
    return f"cycle-{stamp}Z"


def sample_step(config: OnlineEvalConfig, *, cycle_id: str) -> dict[str, Any]:
    """Read new traced runs out of the span store and sample them."""
    cursor_before = read_cursor(config)
    runs, cursor_after = load_runs_from_store(
        config.traces_path,
        after_unix_ns=cursor_before,
    )
    sampled = sample_runs(
        runs,
        limit=config.sample_limit,
        seed=config.sample_seed,
    )
    return {
        "cycle_id": cycle_id,
        "cursor_before_ns": cursor_before,
        "cursor_after_ns": cursor_after,
        "n_available": len(runs),
        "n_sampled": len(sampled),
        "runs": [run.model_dump(mode="json") for run in sampled],
    }


def score_step(
    config: OnlineEvalConfig,
    sample_payload: dict[str, Any],
) -> dict[str, Any]:
    """Score sampled runs, joining ground truth for the adjudicated subset."""
    runs = [TracedRun.model_validate(row) for row in sample_payload["runs"]]
    labels = build_label_source(config)
    scored = score_runs(
        runs,
        labels=labels,
        confidence_floor=config.confidence_floor,
    )
    return {
        "cycle_id": sample_payload["cycle_id"],
        "cursor_before_ns": sample_payload["cursor_before_ns"],
        "cursor_after_ns": sample_payload["cursor_after_ns"],
        "n_scored": len(scored),
        "n_labeled": sum(1 for item in scored if item.is_labeled),
        "scored_runs": [item.model_dump(mode="json") for item in scored],
    }


def aggregate_step(
    config: OnlineEvalConfig,
    score_payload: dict[str, Any],
) -> dict[str, Any]:
    """Persist scored runs, then compute the cycle window and rolling window."""
    scored = [ScoredRun.model_validate(row) for row in score_payload["scored_runs"]]
    cycle_id = str(score_payload["cycle_id"])
    append_scored_runs(config, scored)

    cycle_window = build_window_metrics(
        scored,
        window_id=f"{cycle_id}-cycle",
        min_labeled_n=config.thresholds.min_labeled_n,
    )
    rolling = load_scored_runs(config, tail=config.window_size)
    rolling_window = build_window_metrics(
        rolling,
        window_id=f"{cycle_id}-rolling{config.window_size}",
        min_labeled_n=config.thresholds.min_labeled_n,
    )
    baseline = maybe_promote_baseline(config, rolling_window)

    return {
        "cycle_id": cycle_id,
        "cursor_before_ns": score_payload["cursor_before_ns"],
        "cursor_after_ns": score_payload["cursor_after_ns"],
        "n_scored": score_payload["n_scored"],
        "cycle_window": cycle_window.model_dump(mode="json"),
        "rolling_window": rolling_window.model_dump(mode="json"),
        "baseline_window_id": baseline.window_id if baseline else None,
        "baseline_is_current_window": (
            baseline is not None and baseline.window_id == rolling_window.window_id
        ),
    }


def detect_step(
    config: OnlineEvalConfig,
    aggregate_payload: dict[str, Any],
) -> dict[str, Any]:
    """Compare the rolling window against the frozen baseline."""
    rolling_window = WindowMetrics.model_validate(aggregate_payload["rolling_window"])
    baseline = read_baseline(config)
    if baseline is not None and baseline.window_id == rolling_window.window_id:
        # This cycle's own window was just frozen as the baseline. Comparing it
        # to itself would report a perfect all-clear that means nothing.
        baseline = None
    findings = detect_drift(rolling_window, baseline, config.thresholds)
    return {
        **aggregate_payload,
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "n_breached": sum(
            1 for finding in findings if finding.comparable and finding.breached
        ),
        "n_not_comparable": sum(1 for finding in findings if not finding.comparable),
    }


def alert_step(
    config: OnlineEvalConfig,
    detect_payload: dict[str, Any],
    *,
    started_at: datetime | None = None,
) -> dict[str, Any]:
    """Raise alert conditions, persist the cycle record, advance the cursor."""
    now = datetime.now(tz=UTC)
    cycle_id = str(detect_payload["cycle_id"])
    rolling_window = WindowMetrics.model_validate(detect_payload["rolling_window"])
    cycle_window = WindowMetrics.model_validate(detect_payload["cycle_window"])
    findings = [DriftFinding.model_validate(row) for row in detect_payload["findings"]]
    alerts = evaluate_alerts(
        findings,
        rolling_window,
        cycle_id=cycle_id,
        raised_at=now,
    )
    append_alerts(config, alerts)

    notes: list[str] = []
    if detect_payload.get("baseline_is_current_window"):
        notes.append(
            "This cycle's rolling window was frozen as the baseline. Drift "
            "detection starts from the next cycle."
        )
    if rolling_window.n_runs < config.thresholds.min_window_n:
        notes.append(
            f"Rolling window holds {rolling_window.n_runs} run(s), below the "
            f"alerting minimum of {config.thresholds.min_window_n}."
        )

    record = CycleRecord(
        cycle_id=cycle_id,
        started_at=started_at or now,
        finished_at=now,
        n_sampled=int(detect_payload.get("n_scored", 0)),
        n_scored=int(detect_payload.get("n_scored", 0)),
        cursor_before_ns=int(detect_payload["cursor_before_ns"]),
        cursor_after_ns=int(detect_payload["cursor_after_ns"]),
        cycle_window=cycle_window,
        rolling_window=rolling_window,
        baseline_window_id=detect_payload.get("baseline_window_id"),
        findings=findings,
        alerts=alerts,
        notes=notes,
    )
    append_cycle(config, record)
    write_cursor(config, int(detect_payload["cursor_after_ns"]))

    return {
        "cycle_id": cycle_id,
        "n_alerts": len(alerts),
        "alerts": [alert.model_dump(mode="json") for alert in alerts],
        "summary": format_alert_summary(alerts),
        "cursor_after_ns": record.cursor_after_ns,
    }


def run_cycle(
    config: OnlineEvalConfig,
    *,
    cycle_id: str | None = None,
) -> CycleRecord:
    """Run all five steps in one process. Used by the CLI and by the tests."""
    started = datetime.now(tz=UTC)
    resolved_id = cycle_id or new_cycle_id(started)
    sampled = sample_step(config, cycle_id=resolved_id)
    scored = score_step(config, sampled)
    aggregated = aggregate_step(config, scored)
    detected = detect_step(config, aggregated)
    alert_step(config, detected, started_at=started)
    from online_eval.store import load_cycles

    return load_cycles(config)[-1]


def summarize_cycle(record: CycleRecord) -> str:
    """Human-readable one-cycle summary for the CLI and task logs."""
    lines = [f"cycle {record.cycle_id}"]
    rolling = record.rolling_window
    if rolling is not None:
        macro = "n/a" if rolling.macro_f1 is None else f"{rolling.macro_f1:.4f}"
        lines.append(
            f"  rolling window: n={rolling.n_runs} labeled={rolling.n_labeled} "
            f"macro_f1={macro} low_conf={rolling.low_confidence_rate:.3f} "
            f"guardrail={rolling.guardrail_rate:.3f} "
            f"p95={rolling.p95_latency_ms:.1f}ms"
        )
        lines.append(f"  action mix: {rolling.action_counts}")
    lines.append(f"  baseline: {record.baseline_window_id or 'not frozen yet'}")
    for finding in record.findings:
        if not finding.comparable:
            status = "SKIPPED"
        elif finding.breached:
            status = "BREACH "
        else:
            status = "ok     "
        lines.append(f"  [{status}] {finding.metric}: {finding.note}")
    lines.append(f"  {format_alert_summary(record.alerts)}")
    for note in record.notes:
        lines.append(f"  note: {note}")
    return "\n".join(lines)


def alerts_from_record(record: CycleRecord) -> list[AlertEvent]:
    return list(record.alerts)
