"""Offline agent wiring tests (no API key, stub LLM + mock MCP host)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.config import load_config
from agent.llm import StubPlanner
from agent.mcp_host import MockMcpHost, qualify_tool, split_qualified_tool
from agent.run_log import RunLogWriter
from agent.runner import run_case
from schemas.decisions import Decision
from schemas.loader import load_case_file
from servers.clinical_data.extractor import extract

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_agent_loop_produces_valid_decision_and_run_log(
    tmp_path: Path,
) -> None:
    case = load_case_file(PROJECT_ROOT / "data/cases/case-001.json")
    extraction_result = extract(case.clinical_note)
    host = MockMcpHost(
        extraction_payload=extraction_result.model_dump(mode="json"),
        policy_payload=case.payer_policy.model_dump(mode="json"),
    )
    config = load_config(PROJECT_ROOT)
    writer = RunLogWriter(tmp_path / "runs")
    planner = StubPlanner()

    result = await run_case(
        case,
        host,
        planner,
        config=config,
        writer=writer,
    )

    decision = Decision.model_validate(result.decision.model_dump(mode="json"))
    assert decision.action in {"submit", "request-more-info", "deny-risk"}
    assert len(decision.rationale) >= 10
    assert result.run_log.decision is not None
    assert len(result.run_log.tool_calls) == 2
    tools_called = [record.tool for record in result.run_log.tool_calls]
    assert qualify_tool("clinical-data", "extract_chart") in tools_called
    assert qualify_tool("clinical-data", "get_payer_policy") in tools_called
    assert all("clinic-ops" not in tool for tool in tools_called)

    log_path = writer.path
    assert log_path.exists()
    line = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert line["case_id"] == "case-001"
    assert line["decision"]["action"] == decision.action.value
    assert len(line["tool_calls"]) == 2


def test_qualified_tool_round_trip() -> None:
    qualified = qualify_tool("clinical-data", "extract_chart")
    server, tool = split_qualified_tool(qualified)
    assert server == "clinical-data"
    assert tool == "extract_chart"
