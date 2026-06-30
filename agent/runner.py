"""Prior-auth agent runner: MCP tools + planning loop."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from agent.config import CLINICAL_DATA_SERVER, AgentConfig
from agent.decision_guardrail import (
    evaluate_required_field_guardrail,
    guardrail_audit_payload,
)
from agent.fhir_facts import (
    fuse_extraction_with_fhir,
    mapping_for_policy,
    resolve_fhir_facts,
)
from agent.fhir_mcp import fetch_fhir_bundle
from agent.fhir_resilience import (
    fhir_fallback_audit_payload,
    is_fhir_unavailable_error,
    log_fhir_unavailable_fallback,
)
from agent.llm import PlannerLlm
from agent.mcp_host import (
    McpHost,
    qualify_tool,
    summarize_arguments,
    summarize_result,
)
from agent.run_log import RunLog, RunLogWriter
from schemas.cases import Case
from schemas.decisions import Decision
from schemas.extraction_result import ExtractionResult
from schemas.policies import PayerPolicy
from schemas.run_metrics import PlannerRunMetrics


@dataclass(frozen=True)
class RunResult:
    """Successful unattended agent run for one case."""

    case_id: str
    decision: Decision
    extraction: ExtractionResult
    policy: PayerPolicy
    run_log: RunLog
    log_path: str | None = None


async def run_case(
    case: Case,
    host: McpHost,
    planner: PlannerLlm,
    *,
    config: AgentConfig | None = None,
    writer: RunLogWriter | None = None,
) -> RunResult:
    """Run the full prior-auth workflow for a single case."""
    _ = config
    run_log = RunLog(
        case_id=case.case_id,
        drug=case.drug,
        condition=case.condition,
    )
    try:
        discovered = await host.list_tools()
        extraction = await _call_and_log(
            host,
            run_log,
            qualify_tool(CLINICAL_DATA_SERVER, "extract_chart"),
            {
                "note_text": case.clinical_note,
                "drug": case.drug,
                "condition": case.condition,
            },
        )
        note_extraction = ExtractionResult.model_validate(extraction)

        policy_payload = await _call_and_log(
            host,
            run_log,
            qualify_tool(CLINICAL_DATA_SERVER, "get_payer_policy"),
            {"drug": case.drug, "condition": case.condition},
        )
        policy = PayerPolicy.model_validate(policy_payload)
        extraction_result = await _fuse_fhir_facts_if_available(
            case,
            host,
            run_log,
            note_extraction,
            policy,
        )

        decision = await planner.plan_decision(
            case,
            extraction_result,
            policy,
            discovered,
        )
        validated = Decision.model_validate(decision.model_dump(mode="json"))
        guardrail = evaluate_required_field_guardrail(
            validated,
            extraction_result,
            policy,
        )
        validated = guardrail.decision
        enriched = validated.model_copy(
            update={
                "needs_review": sorted(
                    set(validated.needs_review) | set(extraction_result.needs_review)
                )
            },
        )
        validated = Decision.model_validate(enriched.model_dump(mode="json"))
        if guardrail.triggered:
            run_log.guardrail_event = guardrail_audit_payload(guardrail)
        if extraction_result.field_provenance:
            run_log.field_provenance = dict(extraction_result.field_provenance)
        _validate_proposed_action_not_executed(validated)
        planner_metrics = _planner_metrics(planner)
        run_log.record_decision(validated, planner_metrics=planner_metrics)

        log_path: str | None = None
        if writer is not None:
            path = writer.write(run_log)
            log_path = str(path)

        return RunResult(
            case_id=case.case_id,
            decision=validated,
            extraction=extraction_result,
            policy=policy,
            run_log=run_log,
            log_path=log_path,
        )
    except Exception as exc:
        run_log.record_error(str(exc))
        if writer is not None:
            writer.write(run_log)
        raise


async def _fuse_fhir_facts_if_available(
    case: Case,
    host: McpHost,
    run_log: RunLog,
    note_extraction: ExtractionResult,
    policy: PayerPolicy,
) -> ExtractionResult:
    if not case.patient_id:
        return note_extraction

    mapping = mapping_for_policy(policy)
    if mapping is None:
        return note_extraction

    async def _call(tool: str, arguments: dict[str, Any]) -> Any:
        return await _call_and_log(host, run_log, tool, arguments)

    try:
        bundle = await fetch_fhir_bundle(
            case.patient_id,
            mapping,
            call_tool=_call,
        )
    except Exception as exc:
        if not is_fhir_unavailable_error(exc):
            raise
        log_fhir_unavailable_fallback(case_id=case.case_id, error=exc)
        run_log.fhir_fallback = fhir_fallback_audit_payload(exc)
        return note_extraction

    fhir_facts = resolve_fhir_facts(mapping, bundle)
    return fuse_extraction_with_fhir(
        note_extraction,
        fhir_facts,
        required_fields=policy.required_criteria_fields,
    )


async def _call_and_log(
    host: McpHost,
    run_log: RunLog,
    qualified_name: str,
    arguments: dict[str, Any],
) -> Any:
    started = time.perf_counter()
    result = await host.call_tool(qualified_name, arguments)
    duration_ms = (time.perf_counter() - started) * 1000
    run_log.record_tool_call(
        tool=qualified_name,
        arguments_summary=summarize_arguments(arguments),
        result_summary=summarize_result(result),
        duration_ms=round(duration_ms, 2),
    )
    return result


def _validate_proposed_action_not_executed(decision: Decision) -> None:
    """Phase 4 seam: proposed actions must stay proposals only."""
    if decision.proposed_action is None:
        return
    if decision.proposed_action.server != "clinic-ops":
        msg = "proposed_action must target clinic-ops in Phase 4"
        raise ValueError(msg)


def _planner_metrics(planner: PlannerLlm) -> PlannerRunMetrics | None:
    last_metrics = getattr(planner, "last_metrics", None)
    if last_metrics is None:
        return None
    if isinstance(last_metrics, PlannerRunMetrics):
        return last_metrics
    return None
