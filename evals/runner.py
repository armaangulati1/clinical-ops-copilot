"""Run the agent on labeled cases and collect per-case eval artifacts."""

from __future__ import annotations

import time
from collections.abc import Callable

from agent.config import AgentConfig
from agent.llm import PlannerLlm
from agent.mcp_host import McpHost, MockMcpHost
from agent.run_log import RunLogWriter
from agent.runner import run_case
from evals.metrics.trajectory import score_trajectory
from evals.models import CaseEvalResult
from schemas.loader import DatasetEntry
from servers.clinical_data.extractor import extract


async def run_case_eval(
    entry: DatasetEntry,
    host: McpHost,
    planner: PlannerLlm,
    *,
    config: AgentConfig | None = None,
    writer: RunLogWriter | None = None,
) -> CaseEvalResult:
    """Execute one labeled case and return prediction artifacts."""
    case = entry.case
    truth = entry.label.correct_action.value
    started = time.perf_counter()
    result = await run_case(
        case,
        host,
        planner,
        config=config,
        writer=writer,
    )
    total_latency_ms = (time.perf_counter() - started) * 1000
    predicted = result.decision.action.value
    trajectory = score_trajectory(result.run_log, result.decision)
    proposed = result.decision.proposed_action
    drafted_email: str | None = None
    email_subject: str | None = None
    if proposed is not None and proposed.tool == "draft_email":
        body = proposed.arguments.get("body")
        subject = proposed.arguments.get("subject")
        drafted_email = body if isinstance(body, str) else None
        email_subject = subject if isinstance(subject, str) else None
    planner_metrics = result.run_log.planner_metrics

    return CaseEvalResult(
        case_id=case.case_id,
        predicted_action=predicted,
        truth_action=truth,
        correct=predicted == truth,
        trajectory=trajectory,
        planner_metrics=planner_metrics,
        total_latency_ms=round(total_latency_ms, 2),
        drafted_email=drafted_email,
        email_subject=email_subject,
        missing_fields=list(result.decision.missing_fields),
    )


def build_mock_host(
    entry: DatasetEntry,
    *,
    config: AgentConfig | None = None,
) -> MockMcpHost:
    """Offline MCP host using deterministic stub extraction."""
    extraction = extract(entry.case.clinical_note)
    return MockMcpHost(
        extraction_payload=extraction.model_dump(mode="json"),
        policy_payload=entry.case.payer_policy.model_dump(mode="json"),
        config=config,
    )


async def run_dataset_eval(
    entries: list[DatasetEntry],
    planner: PlannerLlm,
    *,
    host: McpHost | None = None,
    host_factory: Callable[[DatasetEntry], McpHost] | None = None,
    config: AgentConfig | None = None,
    writer: RunLogWriter | None = None,
) -> list[CaseEvalResult]:
    if host is None and host_factory is None:
        msg = "Provide either host or host_factory"
        raise ValueError(msg)

    results: list[CaseEvalResult] = []
    shared_host = host is not None
    for entry in entries:
        if shared_host:
            assert host is not None
            active_host = host
        else:
            assert host_factory is not None
            active_host = host_factory(entry)
        try:
            results.append(
                await run_case_eval(
                    entry,
                    active_host,
                    planner,
                    config=config,
                    writer=writer,
                )
            )
        finally:
            if not shared_host:
                close = getattr(active_host, "close", None)
                if close is not None:
                    await close()
    return results


def aggregate_planner_metrics(
    case_results: list[CaseEvalResult],
) -> tuple[list[float], list[float]]:
    latencies: list[float] = []
    costs: list[float] = []
    for result in case_results:
        if result.planner_metrics is not None:
            latencies.append(result.planner_metrics.latency_ms)
            costs.append(result.planner_metrics.estimated_cost_usd)
        else:
            latencies.append(result.total_latency_ms)
            costs.append(0.0)
    return latencies, costs
