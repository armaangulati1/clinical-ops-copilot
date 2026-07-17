"""Tracer-provider construction for the Phoenix observability layer.

Two entry points:

* ``build_inmemory_tracer`` -- fully offline. Spans are captured in an
  in-memory exporter for deterministic tests and for the ``--in-memory`` mode of
  the eval driver. No Phoenix server, no network, no external account.
* ``register_phoenix_tracer`` -- live. Lazily imports ``phoenix.otel.register``
  to point the tracer at a locally running Phoenix collector. Only needed for
  the interactive UI / span-annotation path of the eval driver.
"""

from __future__ import annotations

from typing import cast

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)
from opentelemetry.trace import Tracer

_TRACER_NAME = "phoenix_obs"


def build_inmemory_tracer(
    name: str = _TRACER_NAME,
) -> tuple[Tracer, InMemorySpanExporter]:
    """Return a tracer whose spans land in an in-memory exporter.

    The exporter's ``get_finished_spans()`` yields the exact OpenInference spans
    Phoenix would ingest, so tests and the offline driver assert against real
    span data without standing up a server.
    """
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider.get_tracer(name), exporter


def register_phoenix_tracer(
    project_name: str = "clinical-ops-copilot",
    *,
    endpoint: str | None = None,
) -> tuple[Tracer, InMemorySpanExporter]:
    """Register a tracer against a locally running Phoenix collector.

    Spans are teed to an in-memory exporter as well, so the caller can compute
    the offline comparison against the same spans that stream to Phoenix.

    Lazily imports ``phoenix.otel`` so the core tracing layer and its tests
    depend only on OpenTelemetry + OpenInference semantic conventions, not on the
    full ``arize-phoenix`` install.
    """
    from phoenix.otel import register

    kwargs: dict[str, object] = {"project_name": project_name}
    if endpoint is not None:
        kwargs["endpoint"] = endpoint
    tracer_provider = register(**kwargs)  # type: ignore[arg-type]
    exporter = InMemorySpanExporter()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = cast(Tracer, tracer_provider.get_tracer(_TRACER_NAME))
    return tracer, exporter
