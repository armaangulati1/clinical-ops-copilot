"""LLM client protocol and Anthropic implementation."""

from __future__ import annotations

import os
import time
from typing import Any, Protocol

import anthropic
from anthropic.types import ToolChoiceToolParam, ToolParam

from agent.config import DECISION_TOOL_NAME
from agent.mcp_host import DiscoveredTool
from schemas.cases import Case
from schemas.decisions import Decision, DecisionAction, ProposedAction
from schemas.extraction_result import ExtractionResult
from schemas.policies import PayerPolicy
from schemas.run_metrics import PlannerRunMetrics, TokenUsage, estimate_planner_cost_usd


class PlannerLlm(Protocol):
    """Interface for the decision-planning LLM."""

    async def plan_decision(
        self,
        case: Case,
        extraction: ExtractionResult,
        policy: PayerPolicy,
        discovered_tools: list[DiscoveredTool],
    ) -> Decision:
        """Produce a schema-valid Decision from case context."""


def decision_tool_schema() -> dict[str, Any]:
    schema = Decision.model_json_schema()
    schema["additionalProperties"] = False
    return {
        "name": DECISION_TOOL_NAME,
        "description": (
            "Record the final prior-auth triage decision. "
            "Include proposed_action for clinic-ops tools when the decision "
            "implies an external effect, but do not assume it will execute."
        ),
        "input_schema": schema,
    }


def mcp_tools_to_anthropic(tools: list[DiscoveredTool]) -> list[dict[str, Any]]:
    """Convert discovered MCP tools to Anthropic tool definitions."""
    anthropic_tools = [decision_tool_schema()]
    for tool in tools:
        if tool.server != "clinic-ops":
            continue
        schema = dict(tool.input_schema)
        schema.setdefault("type", "object")
        schema.setdefault("additionalProperties", False)
        anthropic_tools.append(
            {
                "name": tool.qualified_name,
                "description": tool.description or f"{tool.server} tool {tool.name}",
                "input_schema": schema,
            }
        )
    return anthropic_tools


class AnthropicPlanner(PlannerLlm):
    """Claude-backed planner using structured tool output."""

    def __init__(self, model: str) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            msg = "ANTHROPIC_API_KEY is not set"
            raise RuntimeError(msg)
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._last_metrics: PlannerRunMetrics | None = None

    @property
    def last_metrics(self) -> PlannerRunMetrics | None:
        """Usage and latency from the most recent ``plan_decision`` call."""
        return self._last_metrics

    async def plan_decision(
        self,
        case: Case,
        extraction: ExtractionResult,
        policy: PayerPolicy,
        discovered_tools: list[DiscoveredTool],
    ) -> Decision:
        prompt = _planning_prompt(case, extraction, policy)
        tools = mcp_tools_to_anthropic(discovered_tools)
        started = time.perf_counter()
        message = self._client.messages.create(
            model=self._model,
            max_tokens=2000,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            tools=_cast_tools(tools),
            tool_choice=_cast_tool_choice({"type": "tool", "name": DECISION_TOOL_NAME}),
        )
        latency_ms = (time.perf_counter() - started) * 1000
        input_tokens = message.usage.input_tokens
        output_tokens = message.usage.output_tokens
        self._last_metrics = PlannerRunMetrics(
            latency_ms=round(latency_ms, 2),
            usage=TokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            estimated_cost_usd=estimate_planner_cost_usd(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            ),
            model=self._model,
        )
        for block in message.content:
            if block.type != "tool_use":
                continue
            if block.name != DECISION_TOOL_NAME:
                continue
            if not isinstance(block.input, dict):
                continue
            return Decision.model_validate(block.input)
        msg = "Planner did not return a record_prior_auth_decision tool call"
        raise RuntimeError(msg)


class StubPlanner(PlannerLlm):
    """Deterministic planner for offline wiring tests."""

    def __init__(self) -> None:
        self._last_metrics = PlannerRunMetrics(
            latency_ms=0.0,
            usage=TokenUsage(),
            estimated_cost_usd=0.0,
            model="stub",
        )

    @property
    def last_metrics(self) -> PlannerRunMetrics | None:
        return self._last_metrics

    async def plan_decision(
        self,
        case: Case,
        extraction: ExtractionResult,
        policy: PayerPolicy,
        discovered_tools: list[DiscoveredTool],
    ) -> Decision:
        _ = discovered_tools
        missing = list(extraction.needs_review)
        for field in policy.required_criteria_fields:
            value = getattr(extraction.extraction, field, None)
            if value is None and field not in missing:
                missing.append(field)

        if missing:
            return Decision(
                action=DecisionAction.REQUEST_MORE_INFO,
                confidence=0.7,
                rationale=(
                    "Required policy fields are missing or low confidence; "
                    "request additional documentation before submission."
                ),
                missing_fields=sorted(set(missing)),
                needs_review=sorted(set(missing)),
                proposed_action=ProposedAction(
                    server="clinic-ops",
                    tool="draft_email",
                    arguments={
                        "to": "provider@clinic.example",
                        "subject": f"More info needed for {case.case_id}",
                        "body": f"Please supply: {', '.join(sorted(set(missing)))}",
                    },
                ),
            )

        return Decision(
            action=DecisionAction.SUBMIT,
            confidence=0.85,
            rationale=(
                "Extracted clinical facts meet payer required criteria with "
                "sufficient confidence."
            ),
            missing_fields=[],
            proposed_action=ProposedAction(
                server="clinic-ops",
                tool="create_task",
                arguments={
                    "title": f"Submit PA for {case.drug}",
                    "details": f"Prepare submission for {case.case_id}",
                    "idempotency_key": f"{case.case_id}-submit",
                },
            ),
        )


_SYSTEM_PROMPT = (
    "You are a prior-auth triage agent. Compare extracted clinical facts against "
    "payer policy criteria. Choose submit, request-more-info, or deny-risk. "
    "Use missing_fields only for required policy fields that are genuinely absent "
    "or ambiguous in the extraction. "
    "Use request-more-info when required fields cannot be evaluated yet. "
    "When all required policy fields are present but the clinical facts do NOT "
    "meet payer criteria (thresholds, minimums, or documented failures), choose "
    "deny-risk — not request-more-info. "
    "When the decision implies an external effect, set proposed_action to a "
    "clinic-ops tool call (draft_email, send_email, schedule_followup, or "
    "create_task) with concrete arguments, but assume it will require human "
    "approval before execution."
)


def _planning_prompt(
    case: Case,
    extraction: ExtractionResult,
    policy: PayerPolicy,
) -> str:
    return (
        f"Case ID: {case.case_id}\n"
        f"Drug: {case.drug}\n"
        f"Condition: {case.condition}\n\n"
        f"Payer policy:\n{policy.model_dump_json(indent=2)}\n\n"
        f"Extraction result:\n{extraction.model_dump_json(indent=2)}\n\n"
        f"Clinical note:\n{case.clinical_note}\n\n"
        "Record the final prior-auth decision."
    )


def _cast_tools(tools: list[dict[str, Any]]) -> list[ToolParam]:
    from typing import cast

    return cast(list[ToolParam], tools)


def _cast_tool_choice(payload: dict[str, str]) -> ToolChoiceToolParam:
    from typing import cast

    return cast(ToolChoiceToolParam, payload)
