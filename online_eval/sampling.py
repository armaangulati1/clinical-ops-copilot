"""Reconstruct agent runs from traced spans, then sample them.

The loop's input is a trace, not an agent object. One run is a group of spans
sharing a ``trace_id``, rooted at the ``prior_auth.pipeline`` CHAIN span that
``phoenix_obs.tracing`` already emits. This module does not know how the agent
works; it knows the span contract, which is exactly the coupling a real
observability-driven eval loop has.

Two sources are supported:

* ``load_runs_from_store`` -- the local JSONL span store. Offline, deterministic,
  no server. This is what the tests and the DAG use.
* ``PhoenixSpanSource`` -- a live Arize Phoenix instance, queried through the
  ``phoenix.client`` span API. Lazily imported, exactly like
  ``phoenix_obs.setup.register_phoenix_tracer``, so the optional ``phoenix``
  extra is not needed to run the loop.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from online_eval.models import NANOS_PER_MS, SpanRecord, TracedRun
from online_eval.trace_store import load_span_records

ROOT_SPAN = "prior_auth.pipeline"
GUARDRAIL_SPAN = "guardrail.required_field"
TOOL_SPAN_PREFIX = "mcp.tool."

CASE_ID_ATTR = "prior_auth.case_id"
ACTION_ATTR = "decision.action"
CONFIDENCE_ATTR = "decision.confidence"
NEEDS_REVIEW_ATTR = "decision.needs_review_count"
GUARDRAIL_TRIGGERED_ATTR = "guardrail.triggered"


def _as_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    return default


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return default


def group_spans_by_trace(
    records: list[SpanRecord],
) -> dict[str, list[SpanRecord]]:
    grouped: dict[str, list[SpanRecord]] = defaultdict(list)
    for record in records:
        grouped[record.trace_id].append(record)
    return dict(grouped)


def reconstruct_run(spans: list[SpanRecord]) -> TracedRun | None:
    """Build one ``TracedRun`` from the spans of a single trace.

    Returns ``None`` when the trace has no root pipeline span or the root is
    missing the case id or decision action. A partial trace is dropped rather
    than filled in with defaults, because a silently defaulted decision would
    pollute the very distribution this loop is watching.
    """
    root = next((span for span in spans if span.name == ROOT_SPAN), None)
    if root is None:
        return None
    case_id = root.attributes.get(CASE_ID_ATTR)
    action = root.attributes.get(ACTION_ATTR)
    if not isinstance(case_id, str) or not isinstance(action, str):
        return None

    guardrail = next((span for span in spans if span.name == GUARDRAIL_SPAN), None)
    guardrail_triggered = False
    if guardrail is not None:
        guardrail_triggered = bool(
            guardrail.attributes.get(GUARDRAIL_TRIGGERED_ATTR, False)
        )
    tool_calls = sum(1 for span in spans if span.name.startswith(TOOL_SPAN_PREFIX))

    return TracedRun(
        trace_id=root.trace_id,
        case_id=case_id,
        observed_at=datetime.fromtimestamp(root.end_unix_ns / 1e9, tz=UTC),
        predicted_action=action,
        confidence=_as_float(root.attributes.get(CONFIDENCE_ATTR)),
        latency_ms=round(
            (root.end_unix_ns - root.start_unix_ns) / NANOS_PER_MS,
            3,
        ),
        tool_call_count=tool_calls,
        guardrail_triggered=guardrail_triggered,
        needs_review_count=_as_int(root.attributes.get(NEEDS_REVIEW_ATTR)),
    )


def reconstruct_runs(records: list[SpanRecord]) -> list[TracedRun]:
    """Reconstruct every complete run present in a span batch, oldest first."""
    runs: list[TracedRun] = []
    for spans in group_spans_by_trace(records).values():
        run = reconstruct_run(spans)
        if run is not None:
            runs.append(run)
    runs.sort(key=lambda run: (run.observed_at, run.trace_id))
    return runs


def sample_runs(
    runs: list[TracedRun],
    *,
    limit: int,
    seed: int,
) -> list[TracedRun]:
    """Uniformly sample at most ``limit`` runs, seeded for reproducibility.

    Uniform rather than stratified on purpose: stratifying by predicted action
    would hold the action mix fixed, and the action mix is one of the things the
    drift detector is watching. Sampled runs are returned in observation order
    so the rolling window stays chronological.
    """
    if limit <= 0:
        return []
    if len(runs) <= limit:
        return list(runs)
    rng = random.Random(seed)
    chosen = rng.sample(range(len(runs)), limit)
    return [runs[index] for index in sorted(chosen)]


def load_runs_from_store(
    traces_path: Path,
    *,
    after_unix_ns: int = 0,
) -> tuple[list[TracedRun], int]:
    """Load runs newer than the cursor. Returns the runs and the new cursor.

    The new cursor is the maximum span end time seen, so the next cycle starts
    strictly after this batch and no run is scored twice.
    """
    records = load_span_records(traces_path, after_unix_ns=after_unix_ns)
    if not records:
        return [], after_unix_ns
    new_cursor = max(record.end_unix_ns for record in records)
    return reconstruct_runs(records), new_cursor


class PhoenixSpanSource:
    """Pull spans from a live Phoenix instance instead of the local store.

    Phoenix is the span backend a deployment would actually read from, and the
    project already ships spans to it (``phoenix_obs``). This adapter exists so
    the loop is not structurally tied to the JSONL file.

    Not exercised in this repository's test suite: it needs a running Phoenix
    server, so it is covered by the same optional ``phoenix`` extra as the rest
    of the live path and is imported lazily. Do not read its presence as
    evidence that a live Phoenix query has been run here.
    """

    def __init__(self, project_name: str = "clinical-ops-copilot") -> None:
        self.project_name = project_name

    def fetch(self, *, limit: int = 200) -> list[SpanRecord]:
        from phoenix.client import Client

        client: Any = Client()
        frame: Any = client.spans.get_spans_dataframe(
            project_name=self.project_name,
            limit=limit,
        )
        records: list[SpanRecord] = []
        for row in frame.to_dict(orient="records"):
            attributes = row.get("attributes")
            records.append(
                SpanRecord(
                    trace_id=str(row.get("context.trace_id", "")),
                    span_id=str(row.get("context.span_id", "")),
                    parent_span_id=(
                        str(row["parent_id"]) if row.get("parent_id") else None
                    ),
                    name=str(row.get("name", "")),
                    start_unix_ns=_as_int(row.get("start_time_unix_nano")),
                    end_unix_ns=_as_int(row.get("end_time_unix_nano")),
                    attributes=attributes if isinstance(attributes, dict) else {},
                )
            )
        return records
