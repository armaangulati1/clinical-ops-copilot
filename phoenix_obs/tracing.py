"""OpenInference tracing wrappers for the prior-auth pipeline.

Boundary instrumentation: the decision code under ``agent/`` is not modified.
Spans are produced two ways, both of which read only what the agent already
exposes:

1. Real call-wrapping spans for the two dependency-injected seams that
   ``agent.runner.run_case`` already accepts -- the ``McpHost`` (extractor and
   payer-policy tool calls) and the ``PlannerLlm`` (the planning step). Wrapping
   these requires no agent edits: ``run_case`` receives the wrapped objects.
2. A guardrail span reconstructed from the run's PHI-redacted audit payload
   (``agent.run_log.RunLog.guardrail_event``). The required-field guardrail runs
   *inside* ``run_case`` and is not an injected seam, so its span is emitted from
   the same audit trail the agent already persists, rather than by wrapping the
   call. This is documented explicitly so the trace is not mistaken for a
   deeper hook than it is.

Every value written to a span passes through the repo's own
``schemas.phi_redaction`` helpers, so clinical-note PHI never reaches a trace.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from openinference.semconv.trace import (
    OpenInferenceSpanKindValues,
    SpanAttributes,
)
from opentelemetry.trace import Span, Tracer

from agent.config import AgentConfig
from agent.llm import PlannerLlm
from agent.mcp_host import DiscoveredTool, McpHost, split_qualified_tool
from agent.run_log import RunLogWriter
from agent.runner import RunResult, run_case
from schemas.cases import Case
from schemas.decisions import Decision
from schemas.extraction_result import ExtractionResult
from schemas.phi_redaction import redact_payload, redact_text
from schemas.policies import PayerPolicy
from schemas.run_metrics import PlannerRunMetrics

_JSON_MIME = "application/json"


def _redact_json(value: Any) -> str:
    """Serialize a value to JSON after routing it through PHI redaction."""
    if isinstance(value, dict):
        safe: Any = redact_payload(value)
    elif isinstance(value, str):
        safe = redact_text(value)
    elif isinstance(value, list):
        safe = [redact_payload(v) if isinstance(v, dict) else v for v in value]
    else:
        safe = value
    return json.dumps(safe, ensure_ascii=False, default=str)


def _set_kind(span: Span, kind: OpenInferenceSpanKindValues) -> None:
    span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND, kind.value)


class TracedMcpHost:
    """Wrap an ``McpHost`` so each tool call emits an OpenInference TOOL span.

    Structurally compatible with the ``McpHost`` protocol, so it can be passed
    straight into ``agent.runner.run_case`` in place of the real host.
    """

    def __init__(self, inner: McpHost, tracer: Tracer) -> None:
        self._inner = inner
        self._tracer = tracer

    async def list_tools(self) -> list[DiscoveredTool]:
        return await self._inner.list_tools()

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> Any:
        _, tool_name = split_qualified_tool(qualified_name)
        with self._tracer.start_as_current_span(f"mcp.tool.{tool_name}") as span:
            _set_kind(span, OpenInferenceSpanKindValues.TOOL)
            span.set_attribute(SpanAttributes.TOOL_NAME, tool_name)
            span.set_attribute(SpanAttributes.INPUT_MIME_TYPE, _JSON_MIME)
            span.set_attribute(SpanAttributes.INPUT_VALUE, _redact_json(arguments))
            result = await self._inner.call_tool(qualified_name, arguments)
            span.set_attribute(SpanAttributes.OUTPUT_MIME_TYPE, _JSON_MIME)
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, _redact_json(result))
            return result

    async def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if close is not None:
            await close()


class TracedPlanner:
    """Wrap a ``PlannerLlm`` so the planning step emits an OpenInference LLM span.

    Forwards ``last_metrics`` so ``run_case`` still records planner token/latency
    metrics exactly as it does with the unwrapped planner.
    """

    def __init__(self, inner: PlannerLlm, tracer: Tracer) -> None:
        self._inner = inner
        self._tracer = tracer

    @property
    def last_metrics(self) -> PlannerRunMetrics | None:
        metrics = getattr(self._inner, "last_metrics", None)
        if isinstance(metrics, PlannerRunMetrics):
            return metrics
        return None

    async def plan_decision(
        self,
        case: Case,
        extraction: ExtractionResult,
        policy: PayerPolicy,
        discovered_tools: list[DiscoveredTool],
    ) -> Decision:
        with self._tracer.start_as_current_span("planner.plan_decision") as span:
            _set_kind(span, OpenInferenceSpanKindValues.LLM)
            span.set_attribute(SpanAttributes.INPUT_MIME_TYPE, _JSON_MIME)
            span.set_attribute(
                SpanAttributes.INPUT_VALUE,
                _redact_json(
                    {
                        "case_id": case.case_id,
                        "drug": case.drug,
                        "condition": case.condition,
                        "required_criteria_fields": list(
                            policy.required_criteria_fields
                        ),
                        "extraction_needs_review": list(extraction.needs_review),
                    }
                ),
            )
            decision = await self._inner.plan_decision(
                case, extraction, policy, discovered_tools
            )
            span.set_attribute(SpanAttributes.OUTPUT_MIME_TYPE, _JSON_MIME)
            span.set_attribute(
                SpanAttributes.OUTPUT_VALUE,
                _redact_json(
                    {
                        "action": decision.action.value,
                        "confidence": decision.confidence,
                        "rationale": decision.rationale,
                    }
                ),
            )
            span.set_attribute("decision.action", decision.action.value)
            span.set_attribute("decision.confidence", decision.confidence)
            metrics = self.last_metrics
            if metrics is not None:
                if metrics.model is not None:
                    span.set_attribute(SpanAttributes.LLM_MODEL_NAME, metrics.model)
                span.set_attribute(
                    SpanAttributes.LLM_TOKEN_COUNT_TOTAL, metrics.usage.total_tokens
                )
            return decision


@contextmanager
def pipeline_span(tracer: Tracer, case_id: str) -> Iterator[Span]:
    """Open the root CHAIN span for one case run."""
    with tracer.start_as_current_span("prior_auth.pipeline") as span:
        _set_kind(span, OpenInferenceSpanKindValues.CHAIN)
        span.set_attribute("prior_auth.case_id", case_id)
        yield span


def _emit_guardrail_span(tracer: Tracer, run_result: RunResult) -> None:
    """Emit the guardrail span from the run's PHI-redacted audit payload.

    The required-field guardrail executes inside ``run_case`` (not an injected
    seam), so its span is reconstructed from ``run_log.guardrail_event`` rather
    than by wrapping the call.
    """
    event = run_result.run_log.guardrail_event or {}
    triggered = bool(event)
    with tracer.start_as_current_span("guardrail.required_field") as span:
        _set_kind(span, OpenInferenceSpanKindValues.GUARDRAIL)
        span.set_attribute("guardrail.name", "required_field")
        span.set_attribute("guardrail.triggered", triggered)
        span.set_attribute("guardrail.source", "run_log.guardrail_event")
        if triggered:
            original = event.get("original_action")
            overridden = event.get("overridden_action")
            if isinstance(original, str):
                span.set_attribute("guardrail.original_action", original)
            if isinstance(overridden, str):
                span.set_attribute("guardrail.overridden_action", overridden)
            missing = event.get("missing_fields")
            if isinstance(missing, list):
                span.set_attribute("guardrail.missing_fields", json.dumps(missing))
        span.set_attribute(SpanAttributes.OUTPUT_MIME_TYPE, _JSON_MIME)
        span.set_attribute(SpanAttributes.OUTPUT_VALUE, _redact_json(event))


def _set_decision_attributes(span: Span, decision: Decision) -> None:
    span.set_attribute("decision.action", decision.action.value)
    span.set_attribute("decision.confidence", decision.confidence)
    span.set_attribute("decision.needs_review_count", len(decision.needs_review))
    span.set_attribute(SpanAttributes.OUTPUT_MIME_TYPE, _JSON_MIME)
    span.set_attribute(
        SpanAttributes.OUTPUT_VALUE,
        _redact_json(
            {
                "action": decision.action.value,
                "confidence": decision.confidence,
                "missing_fields": list(decision.missing_fields),
            }
        ),
    )


async def traced_run_case(
    case: Case,
    host: McpHost,
    planner: PlannerLlm,
    tracer: Tracer,
    *,
    config: AgentConfig | None = None,
    writer: RunLogWriter | None = None,
) -> RunResult:
    """Run ``agent.runner.run_case`` under a root span with wrapped seams.

    ``run_case`` itself is called unmodified; it receives the traced host and
    planner and emits nothing Phoenix-specific. All OpenInference spans are
    produced by this wrapper.
    """
    with pipeline_span(tracer, case.case_id) as root:
        traced_host = TracedMcpHost(host, tracer)
        traced_planner = TracedPlanner(planner, tracer)
        result = await run_case(
            case,
            traced_host,
            traced_planner,
            config=config,
            writer=writer,
        )
        _set_decision_attributes(root, result.decision)
        _emit_guardrail_span(tracer, result)
        return result
