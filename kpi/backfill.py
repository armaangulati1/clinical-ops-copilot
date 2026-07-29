"""Recover operational signals for runs recorded before the instrumentation.

`evals/results/*.json` files written before the KPI layer existed carry no
approval-gate or guardrail outcome, so the human intervention KPI cannot be
computed from them. Those outcomes are recoverable without re-running a
model: the run log written alongside the eval holds the full decision for
every case, and the approval policy is a pure function of a decision.

This module replays that pure function over the recorded decisions. It never
touches a model, never changes a prediction, and refuses to run when the run
log is not provably the same run as the eval artifact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agent.approval_policy import requires_approval
from evals.models import EvalResults
from schemas.decisions import Decision


class RunLogMismatchError(RuntimeError):
    """Raised when a run log does not provably match an eval artifact."""


@dataclass(frozen=True)
class RecordedRunSignals:
    """Approval-gate and guardrail outcome for one recorded decision."""

    case_id: str
    action: str
    approval_required: bool
    guardrail_triggered: bool


@dataclass(frozen=True)
class BackfillSummary:
    """What a backfill changed, for reporting and for tests."""

    n_cases: int
    n_approval_required: int
    n_guardrail_triggered: int


def load_run_log_signals(run_log_path: Path) -> dict[str, RecordedRunSignals]:
    """Read approval and guardrail outcomes out of a run-log JSONL."""
    signals: dict[str, RecordedRunSignals] = {}
    text = run_log_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        decision_payload = row.get("decision")
        if decision_payload is None:
            continue
        decision = Decision.model_validate(decision_payload)
        case_id = str(row["case_id"])
        signals[case_id] = RecordedRunSignals(
            case_id=case_id,
            action=decision.action.value,
            approval_required=requires_approval(decision),
            guardrail_triggered=row.get("guardrail_event") is not None,
        )
    return signals


def _assert_same_run(
    results: EvalResults,
    signals: dict[str, RecordedRunSignals],
) -> None:
    """Refuse to backfill unless the log demonstrably describes this run."""
    for result in results.case_results:
        signal = signals.get(result.case_id)
        if signal is None:
            msg = (
                f"Run log has no entry for {result.case_id}; it does not "
                "cover this eval run."
            )
            raise RunLogMismatchError(msg)
        if signal.action != result.predicted_action:
            msg = (
                f"Run log for {result.case_id} recorded action "
                f"{signal.action!r} but the eval artifact recorded "
                f"{result.predicted_action!r}; these are different runs."
            )
            raise RunLogMismatchError(msg)


def backfill_intervention_signals(
    results: EvalResults,
    signals: dict[str, RecordedRunSignals],
) -> BackfillSummary:
    """Populate approval and guardrail flags in place on an eval artifact.

    Only the two new fields are written. Predictions, metrics, and every
    other recorded value are left exactly as the original run produced them.
    """
    _assert_same_run(results, signals)
    n_approval = 0
    n_guardrail = 0
    for result in results.case_results:
        signal = signals[result.case_id]
        result.approval_required = signal.approval_required
        result.guardrail_triggered = signal.guardrail_triggered
        n_approval += signal.approval_required
        n_guardrail += signal.guardrail_triggered
    return BackfillSummary(
        n_cases=len(results.case_results),
        n_approval_required=n_approval,
        n_guardrail_triggered=n_guardrail,
    )


def backfill_results_file(
    results_path: Path,
    run_log_path: Path,
) -> BackfillSummary:
    """Backfill an eval-results JSON file from its run log, in place."""
    results = EvalResults.model_validate_json(results_path.read_text(encoding="utf-8"))
    summary = backfill_intervention_signals(
        results,
        load_run_log_signals(run_log_path),
    )
    results_path.write_text(
        results.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return summary
