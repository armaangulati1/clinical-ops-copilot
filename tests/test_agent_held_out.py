"""Network tests: agent runs on 10 held-out cases with Claude + real MCP servers."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent.config import load_config
from agent.held_out import HELD_OUT_CASE_IDS
from agent.llm import AnthropicPlanner
from agent.mcp_host import StdioMcpHost
from agent.run_log import RunLogWriter
from agent.runner import run_case
from schemas.decisions import Decision
from schemas.loader import load_case_file

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _require_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.network
@pytest.mark.anyio
async def test_held_out_cases_emit_valid_decisions_and_logs(
    tmp_path: Path,
) -> None:
    _require_api_key()
    config = load_config(PROJECT_ROOT)
    writer = RunLogWriter(tmp_path / "runs")
    host = await StdioMcpHost.connect(config)
    planner = AnthropicPlanner(config.anthropic_model)

    try:
        for case_id in HELD_OUT_CASE_IDS:
            case = load_case_file(PROJECT_ROOT / "data/cases" / f"{case_id}.json")
            result = await run_case(
                case,
                host,
                planner,
                config=config,
                writer=writer,
            )
            decision = Decision.model_validate(result.decision.model_dump(mode="json"))
            assert decision.action in {"submit", "request-more-info", "deny-risk"}
            assert len(result.run_log.tool_calls) >= 2
            assert result.run_log.decision is not None
    finally:
        await host.close()

    lines = writer.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == len(HELD_OUT_CASE_IDS)
    for line in lines:
        payload = json.loads(line)
        Decision.model_validate(payload["decision"])
        assert payload["tool_calls"], "expected tool-call audit trail"
