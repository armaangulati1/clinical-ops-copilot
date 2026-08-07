"""Append-only JSONL store of emitted spans.

This is the seam between the application and the eval loop. The application
writes spans here (via ``online_eval.otel_sink``); the loop reads them and never
touches the application. That separation is the point: a real online-eval loop
does not call the agent, it reads what the agent already emitted, which is why
this module depends on nothing heavier than pydantic and why the loop can run in
an orchestrator worker that has no model client installed.

JSONL rather than a database because the store is append-only, is trivially
inspectable with ``tail``, and needs no service to stand up. The trade-off is
real: reads are a full scan, so this does not scale to production trace volume.
A deployment would point ``load_span_records`` at Phoenix or another span
backend instead (see ``online_eval.sampling.PhoenixSpanSource``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from online_eval.models import SpanRecord


def append_span_records(path: Path, records: Iterable[SpanRecord]) -> int:
    """Append span records as JSON lines. Returns how many were written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(record.model_dump_json())
            handle.write("\n")
            written += 1
    return written


def iter_span_records(path: Path) -> Iterator[SpanRecord]:
    """Stream span records from the store, skipping blank lines."""
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            yield SpanRecord.model_validate_json(stripped)


def load_span_records(
    path: Path,
    *,
    after_unix_ns: int = 0,
) -> list[SpanRecord]:
    """Load span records whose span ended strictly after ``after_unix_ns``.

    The cursor is applied per span rather than per trace, then the sampler
    regroups by ``trace_id``. A trace that straddles the cursor therefore
    contributes its late spans only; the sampler drops any trace whose root span
    is missing, so a straddling trace is skipped rather than half-scored.
    """
    return [
        record
        for record in iter_span_records(path)
        if record.end_unix_ns > after_unix_ns
    ]


def append_jsonl(path: Path, payload: dict[str, object]) -> None:
    """Append one JSON object as a line (used for cycles and alerts)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, default=str))
        handle.write("\n")


def read_jsonl(path: Path) -> list[dict[str, object]]:
    """Read a JSONL file into a list of dicts. Missing file reads as empty."""
    if not path.exists():
        return []
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                rows.append(parsed)
    return rows
