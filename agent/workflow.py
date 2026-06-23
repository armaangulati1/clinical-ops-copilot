"""Gated prior-auth workflow orchestration."""

from __future__ import annotations

from agent.config import AgentConfig
from agent.gate import ApprovalGate
from agent.injection_guard import InjectionScanResult, scan_and_sanitize
from agent.llm import PlannerLlm
from agent.mcp_host import McpHost
from agent.run_log import RunLogWriter
from agent.runner import run_case
from schemas.approval import WorkflowResult
from schemas.cases import Case


async def run_case_with_gate(
    case: Case,
    host: McpHost,
    planner: PlannerLlm,
    gate: ApprovalGate,
    *,
    config: AgentConfig | None = None,
    writer: RunLogWriter | None = None,
) -> WorkflowResult:
    """Run the agent loop and apply the human approval gate."""
    injection_scan = scan_and_sanitize(case.clinical_note)
    sanitized_case = _case_with_sanitized_note(case, injection_scan)
    run_result = await run_case(
        sanitized_case,
        host,
        planner,
        config=config,
        writer=writer,
    )
    return await gate.process_agent_result(
        case,
        run_result.decision,
        run_result.extraction,
        run_result.policy,
        run_result.run_log,
        injection_scan=injection_scan,
    )


def _case_with_sanitized_note(case: Case, scan: InjectionScanResult) -> Case:
    if scan.sanitized_text == case.clinical_note:
        return case
    return case.model_copy(update={"clinical_note": scan.sanitized_text})
