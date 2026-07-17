"""Arize Phoenix / OpenInference observability layer for the prior-auth agent.

Demo-scope, independent demonstration. This package instruments the existing
agent pipeline with OpenInference spans (the tracing format Arize Phoenix
consumes) without modifying any code under ``agent/``. See ``README.md`` in this
package for the honest framing and the full span list.
"""

from __future__ import annotations

from phoenix_obs.setup import build_inmemory_tracer, register_phoenix_tracer
from phoenix_obs.tracing import (
    TracedMcpHost,
    TracedPlanner,
    pipeline_span,
    traced_run_case,
)

__all__ = [
    "TracedMcpHost",
    "TracedPlanner",
    "build_inmemory_tracer",
    "pipeline_span",
    "register_phoenix_tracer",
    "traced_run_case",
]
