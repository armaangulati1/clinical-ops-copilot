"""OpenTelemetry exporter that writes spans into the JSONL trace store.

This is the only place the online-eval package touches the OTel SDK, and it sits
on the *application* side of the seam: the app exports spans, the loop reads
them. Implementing a real ``SpanExporter`` rather than reaching into an
in-memory list means the spans that reach the store are the same spans that
would reach Phoenix, through the same processor pipeline, with the same
attribute encoding.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Tracer

from online_eval.models import SpanRecord
from online_eval.trace_store import append_span_records

_TRACER_NAME = "online_eval.traffic"


def _coerce_attribute(value: Any) -> Any:
    """Reduce an OTel attribute value to something JSON can carry."""
    if isinstance(value, str | bool | int | float) or value is None:
        return value
    if isinstance(value, Sequence):
        return [_coerce_attribute(item) for item in value]
    return str(value)


def span_to_record(span: ReadableSpan) -> SpanRecord | None:
    """Flatten a finished span into a storable record.

    Returns ``None`` for a span with no context or no end time; an unfinished
    span cannot be scored and is dropped rather than stored with a zero
    duration that would silently deflate the latency percentiles.
    """
    context = span.get_span_context()
    if context is None or span.start_time is None or span.end_time is None:
        return None
    parent = span.parent
    attributes = {
        key: _coerce_attribute(value) for key, value in (span.attributes or {}).items()
    }
    return SpanRecord(
        trace_id=format(context.trace_id, "032x"),
        span_id=format(context.span_id, "016x"),
        parent_span_id=format(parent.span_id, "016x") if parent is not None else None,
        name=span.name,
        start_unix_ns=span.start_time,
        end_unix_ns=span.end_time,
        attributes=attributes,
    )


class JsonlSpanExporter(SpanExporter):
    """Append every finished span to the JSONL trace store."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._shutdown = False

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if self._shutdown:
            return SpanExportResult.FAILURE
        records = [
            record for record in (span_to_record(span) for span in spans) if record
        ]
        append_span_records(self._path, records)
        return SpanExportResult.SUCCESS

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        return True

    def shutdown(self) -> None:
        self._shutdown = True


def build_store_tracer(path: Path) -> tuple[Tracer, JsonlSpanExporter]:
    """Tracer whose finished spans land in the JSONL trace store at ``path``."""
    exporter = JsonlSpanExporter(path)
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer(_TRACER_NAME), exporter
