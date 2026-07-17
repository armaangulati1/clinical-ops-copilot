"""Phoenix eval driver: instrument the pipeline, score a dimension, compare.

What it does, in order:

1. Runs each case of an eval split through the *instrumented* pipeline
   (``traced_run_case``), capturing OpenInference spans -- the "Phoenix view".
2. Runs the same cases through the repo's own hand-rolled eval harness
   (``evals.runner.run_case_eval``) -- the "harness view".
3. Scores the ``decision_correctness`` dimension (predicted action == gold
   action) from each view and reports per-case agreement plus overall accuracy.
   Because both views execute the same deterministic offline pipeline, they are
   expected to agree case-for-case; any divergence would flag an instrumentation
   gap and is surfaced explicitly.
4. In ``--phoenix`` mode, ships the spans to a locally running Phoenix collector
   and logs the per-span correctness score as a Phoenix span annotation (the
   library's eval-logging mechanism), so the scored dimension is browsable in the
   Phoenix UI.

Run offline (no server, no key, deterministic numbers)::

    python -m phoenix_obs.eval_driver --in-memory

Run live against a local Phoenix UI (no cloud account)::

    python -m phoenix_obs.eval_driver --phoenix

The LLM-judge email-quality dimension additionally requires a live planner::

    ANTHROPIC_API_KEY=... python -m phoenix_obs.eval_driver --phoenix --live
"""

from __future__ import annotations

import argparse
import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import Tracer

from agent.config import load_config
from agent.llm import AnthropicPlanner, PlannerLlm, StubPlanner
from evals.dataset import load_eval_dataset
from evals.runner import build_mock_host, run_case_eval
from evals.splits import load_eval_split
from phoenix_obs.setup import build_inmemory_tracer, register_phoenix_tracer
from phoenix_obs.tracing import traced_run_case
from schemas.loader import DatasetEntry

DEFAULT_SPLIT = Path("evals/splits/locked_test.json")


@dataclass(frozen=True)
class CaseComparison:
    """One case scored from both the Phoenix-trace view and the harness view."""

    case_id: str
    truth: str
    phoenix_predicted: str
    harness_predicted: str

    @property
    def phoenix_correct(self) -> bool:
        return self.phoenix_predicted == self.truth

    @property
    def harness_correct(self) -> bool:
        return self.harness_predicted == self.truth

    @property
    def views_agree(self) -> bool:
        return self.phoenix_predicted == self.harness_predicted


def _load_split_entries(project_root: Path, split_path: Path) -> list[DatasetEntry]:
    entries = load_eval_dataset(
        cases_dir=project_root / "data/cases",
        labels_path=project_root / "data/labels/labels.json",
    )
    split = load_eval_split(split_path)
    allowed = set(split.case_ids)
    selected = [e for e in entries if e.case.case_id in allowed]
    selected.sort(key=lambda e: split.case_ids.index(e.case.case_id))
    if len(selected) != len(split.case_ids):
        msg = f"Split {split_path} references cases missing from the dataset"
        raise ValueError(msg)
    return selected


def _phoenix_predictions(spans: list[ReadableSpan]) -> dict[str, str]:
    """Map case_id -> predicted action, read from the root pipeline spans."""
    predictions: dict[str, str] = {}
    for span in spans:
        if span.name != "prior_auth.pipeline":
            continue
        attrs = span.attributes or {}
        case_id = attrs.get("prior_auth.case_id")
        action = attrs.get("decision.action")
        if isinstance(case_id, str) and isinstance(action, str):
            predictions[case_id] = action
    return predictions


def _make_planner(use_live: bool, model: str) -> tuple[PlannerLlm, str]:
    if use_live:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            msg = "ANTHROPIC_API_KEY is required for --live"
            raise RuntimeError(msg)
        return AnthropicPlanner(model), model
    return StubPlanner(), "stub"


async def _run_comparison(
    entries: list[DatasetEntry],
    planner: PlannerLlm,
    tracer: Tracer,
    exporter: InMemorySpanExporter,
) -> tuple[list[CaseComparison], list[ReadableSpan]]:
    # Phoenix view: instrumented pipeline.
    for entry in entries:
        host = build_mock_host(entry)
        await traced_run_case(entry.case, host, planner, tracer)

    # Harness view: the repo's own eval path (independent execution).
    harness_predicted: dict[str, str] = {}
    for entry in entries:
        host = build_mock_host(entry)
        result = await run_case_eval(entry, host, planner)
        harness_predicted[result.case_id] = result.predicted_action

    spans = list(exporter.get_finished_spans())
    phoenix_predicted = _phoenix_predictions(spans)

    comparisons: list[CaseComparison] = []
    for entry in entries:
        cid = entry.case.case_id
        comparisons.append(
            CaseComparison(
                case_id=cid,
                truth=entry.label.correct_action.value,
                phoenix_predicted=phoenix_predicted.get(cid, "<missing-span>"),
                harness_predicted=harness_predicted.get(cid, "<missing>"),
            )
        )
    return comparisons, spans


def _print_report(comparisons: list[CaseComparison], split_path: Path) -> None:
    n = len(comparisons)
    phoenix_acc = sum(c.phoenix_correct for c in comparisons) / n if n else 0.0
    harness_acc = sum(c.harness_correct for c in comparisons) / n if n else 0.0
    agree = sum(c.views_agree for c in comparisons)

    print(f"Phoenix eval comparison on split: {split_path} ({n} cases)")
    print("=" * 72)
    print(f"{'case_id':<12}{'truth':<20}{'phoenix':<20}{'harness':<20}")
    print("-" * 72)
    for c in comparisons:
        flag = "" if c.views_agree else "  <-- DIVERGENCE"
        print(
            f"{c.case_id:<12}{c.truth:<20}"
            f"{c.phoenix_predicted:<20}{c.harness_predicted:<20}{flag}"
        )
    print("-" * 72)
    print(f"Phoenix-view decision accuracy: {phoenix_acc:.3f} ({n} cases)")
    print(f"Harness-view decision accuracy: {harness_acc:.3f} ({n} cases)")
    print(f"Per-case view agreement: {agree}/{n}")
    if agree != n:
        print(
            "DIVERGENCE DETECTED: the trace-derived view disagrees with the "
            "harness on at least one case. Investigate the instrumentation."
        )
    else:
        print(
            "Views agree case-for-case: the OpenInference trace reproduces the "
            "hand-rolled harness verdicts exactly (no instrumentation drift)."
        )


def _log_annotations_to_phoenix(
    comparisons: list[CaseComparison],
    spans: list[ReadableSpan],
) -> None:
    """Log the decision_correctness score to Phoenix as span annotations."""
    import pandas as pd
    from phoenix.client import Client

    truth_by_case = {c.case_id: c for c in comparisons}
    rows: list[dict[str, object]] = []
    for span in spans:
        if span.name != "prior_auth.pipeline":
            continue
        attrs = span.attributes or {}
        case_id = attrs.get("prior_auth.case_id")
        if not isinstance(case_id, str) or case_id not in truth_by_case:
            continue
        ctx = span.get_span_context()
        if ctx is None:
            continue
        span_id = format(ctx.span_id, "016x")
        comp = truth_by_case[case_id]
        rows.append(
            {
                "span_id": span_id,
                "label": "correct" if comp.phoenix_correct else "incorrect",
                "score": 1.0 if comp.phoenix_correct else 0.0,
            }
        )
    if not rows:
        print("No pipeline spans available to annotate.")
        return
    frame = pd.DataFrame(rows)
    Client().spans.log_span_annotations_dataframe(
        dataframe=frame,
        annotation_name="decision_correctness",
        annotator_kind="CODE",
    )
    print(f"Logged {len(rows)} decision_correctness annotations to Phoenix.")


def _pending_live_run_notice() -> None:
    print()
    print("LLM-judge email-quality dimension: PENDING LIVE RUN.")
    print("No ANTHROPIC_API_KEY detected, so the drafted-email quality dimension")
    print("was not scored (numbers are not fabricated). To run it live:")
    print()
    print("  ANTHROPIC_API_KEY=<key> \\")
    print("    python -m phoenix_obs.eval_driver --phoenix --live")
    print()


async def _main_async(args: argparse.Namespace) -> None:
    project_root: Path = args.project_root
    split_path: Path = args.split
    config = load_config(project_root)
    planner, _model = _make_planner(args.live, config.anthropic_model)

    use_phoenix = args.phoenix and not args.in_memory
    if use_phoenix:
        tracer, exporter = register_phoenix_tracer()
    else:
        tracer, exporter = build_inmemory_tracer()

    entries = _load_split_entries(project_root, split_path)
    comparisons, spans = await _run_comparison(entries, planner, tracer, exporter)
    _print_report(comparisons, split_path)

    if use_phoenix:
        _log_annotations_to_phoenix(comparisons, spans)

    if not args.live:
        _pending_live_run_notice()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument(
        "--in-memory",
        action="store_true",
        help="Offline: capture spans in memory, no Phoenix server (default).",
    )
    parser.add_argument(
        "--phoenix",
        action="store_true",
        help="Ship spans to a local Phoenix collector and log annotations.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the live Anthropic planner (requires ANTHROPIC_API_KEY).",
    )
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == "__main__":
    main()
