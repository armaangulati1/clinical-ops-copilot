"""End-to-end path sandbox checks through the agent MCP host."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.config import AgentConfig
from agent.mcp_host import MockMcpHost, qualify_tool

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_agent_rejects_chart_path_traversal(tmp_path: Path) -> None:
    charts = tmp_path / "data" / "charts"
    charts.mkdir(parents=True)
    config = AgentConfig(project_root=tmp_path, runs_dir=tmp_path / "runs")
    host = MockMcpHost(
        extraction_payload={},
        policy_payload={},
        config=config,
    )

    with pytest.raises(RuntimeError, match="path not accessible"):
        await host.call_tool(
            qualify_tool("clinical-data", "extract_chart"),
            {"chart_path": "../../etc/passwd"},
        )
