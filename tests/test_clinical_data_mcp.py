"""MCP integration tests for the clinical-data server."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from fhir.resources.patient import Patient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import TextContent

from schemas.extraction import Extraction
from schemas.extraction_result import ExtractionResult
from schemas.loader import load_case_file
from schemas.policies import PayerPolicy
from servers.clinical_data.config import ServerConfig
from servers.clinical_data.server import configure, mcp

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PHASE1_NOTE = load_case_file(PROJECT_ROOT / "data/cases/case-001.json").clinical_note


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def server_config(tmp_path: Path) -> ServerConfig:
    chart_root = tmp_path / "charts"
    chart_root.mkdir()
    (chart_root / "case-001-note.txt").write_text(PHASE1_NOTE, encoding="utf-8")
    config = ServerConfig(chart_roots=(chart_root,))
    configure(config)
    return config


@pytest.fixture
async def memory_client(
    server_config: ServerConfig,
) -> AsyncGenerator[ClientSession, None]:
    _ = server_config
    async with create_connected_server_and_client_session(
        mcp,
        raise_exceptions=True,
    ) as session:
        yield session


@pytest.fixture
def stdio_server_params(tmp_path: Path) -> StdioServerParameters:
    chart_root = tmp_path / "charts"
    chart_root.mkdir()
    (chart_root / "case-001-note.txt").write_text(PHASE1_NOTE, encoding="utf-8")
    env = os.environ.copy()
    env["CLINICAL_DATA_CHART_ROOT"] = str(chart_root)
    return StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "servers.clinical_data"],
        cwd=PROJECT_ROOT,
        env=env,
    )


@pytest.mark.anyio
async def test_memory_client_lists_tools_and_resources(
    memory_client: ClientSession,
) -> None:
    tools = await memory_client.list_tools()
    tool_names = {tool.name for tool in tools.tools}
    assert tool_names == {
        "get_patient_record",
        "get_payer_policy",
        "extract_chart",
        "extract_oncology_chart",
    }

    resources = await memory_client.list_resources()
    resource_uris = {str(resource.uri) for resource in resources.resources}
    assert "patient://patient-001" in resource_uris


@pytest.mark.anyio
async def test_extract_chart_on_phase1_note(memory_client: ClientSession) -> None:
    result = await memory_client.call_tool(
        "extract_chart",
        {"note_text": PHASE1_NOTE},
    )
    assert result.isError is False
    assert result.structuredContent is not None
    parsed = ExtractionResult.model_validate(result.structuredContent)
    extraction = Extraction.model_validate(parsed.extraction.model_dump(mode="json"))
    assert extraction.patient_name == "Jordan Blake"
    assert extraction.das28_score == 4.8


@pytest.mark.anyio
async def test_get_patient_record_returns_fhir_valid_json(
    memory_client: ClientSession,
) -> None:
    result = await memory_client.call_tool(
        "get_patient_record",
        {"patient_id": "patient-001"},
    )
    assert result.isError is False
    assert result.structuredContent is not None
    patient = Patient.model_validate(result.structuredContent)
    assert patient.id == "patient-001"


@pytest.mark.anyio
async def test_get_payer_policy_returns_phase1_model(
    memory_client: ClientSession,
) -> None:
    result = await memory_client.call_tool(
        "get_payer_policy",
        {"drug": "Humira", "condition": "rheumatoid arthritis"},
    )
    assert result.isError is False
    policy = PayerPolicy.model_validate(result.structuredContent)
    assert "das28_score" in policy.required_criteria_fields


@pytest.mark.anyio
async def test_extract_chart_rejects_path_traversal(
    memory_client: ClientSession,
) -> None:
    result = await memory_client.call_tool(
        "extract_chart",
        {"chart_path": "../../etc/passwd"},
    )
    assert result.isError is True
    assert result.content
    block = result.content[0]
    assert isinstance(block, TextContent)
    assert "path not accessible" in block.text.lower()


@pytest.mark.anyio
async def test_stdio_client_lists_tools_and_calls_tools(
    stdio_server_params: StdioServerParameters,
) -> None:
    async with stdio_client(stdio_server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert "extract_chart" in tool_names
            assert "get_patient_record" in tool_names

            resources = await session.list_resources()
            assert resources.resources

            extract_result = await session.call_tool(
                "extract_chart",
                {"note_text": PHASE1_NOTE},
            )
            assert extract_result.isError is False
            parsed = ExtractionResult.model_validate(extract_result.structuredContent)
            extraction = Extraction.model_validate(
                parsed.extraction.model_dump(mode="json")
            )
            assert extraction.age == 52

            patient_result = await session.call_tool(
                "get_patient_record",
                {"patient_id": "patient-001"},
            )
            assert patient_result.isError is False
            patient = Patient.model_validate(patient_result.structuredContent)
            assert patient.id == "patient-001"
