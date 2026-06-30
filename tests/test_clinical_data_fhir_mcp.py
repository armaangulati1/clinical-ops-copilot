"""FHIR-mode MCP integration tests for clinical-data (via stdio client)."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from fhir_client.models import Condition, MedicationRequest, Observation, Patient

PROJECT_ROOT = Path(__file__).resolve().parents[1]

KNOWN_PATIENT_ID = "1122"
LOINC_PATIENT_ID = "1652"
A1C_LOINC = "http://loinc.org|4548-4"
HAPI_SKIP = "local HAPI FHIR server not reachable"


def _tool_list_payload(structured_content: object) -> list[object]:
    if isinstance(structured_content, list):
        return structured_content
    if isinstance(structured_content, dict) and "result" in structured_content:
        result = structured_content["result"]
        if isinstance(result, list):
            return result
    msg = f"Unexpected MCP list payload: {structured_content!r}"
    raise AssertionError(msg)


def _fhir_base_url() -> str:
    return os.environ.get("FHIR_BASE_URL", "http://localhost:8080/fhir").rstrip("/")


def _hapi_reachable() -> bool:
    try:
        response = httpx.get(f"{_fhir_base_url()}/metadata", timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


@pytest.fixture
def fhir_stdio_server_params(tmp_path: Path) -> StdioServerParameters:
    chart_root = tmp_path / "charts"
    chart_root.mkdir()
    env = os.environ.copy()
    env["CLINICAL_DATA_SOURCE"] = "fhir"
    env["FHIR_BASE_URL"] = _fhir_base_url()
    env["CLINICAL_DATA_CHART_ROOT"] = str(chart_root)
    return StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "servers.clinical_data"],
        cwd=PROJECT_ROOT,
        env=env,
    )


@pytest.mark.anyio
@pytest.mark.network
@pytest.mark.skipif(not _hapi_reachable(), reason=HAPI_SKIP)
async def test_fhir_mode_lists_tools_and_resources(
    fhir_stdio_server_params: StdioServerParameters,
) -> None:
    async with stdio_client(fhir_stdio_server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            tool_names = {tool.name for tool in tools.tools}
            assert {
                "get_patient_record",
                "get_patient_observations",
                "get_patient_conditions",
                "get_patient_medications",
            }.issubset(tool_names)

            resources = await session.list_resources()
            resource_uris = {str(resource.uri) for resource in resources.resources}
            assert f"patient://{KNOWN_PATIENT_ID}" in resource_uris


@pytest.mark.anyio
@pytest.mark.network
@pytest.mark.skipif(not _hapi_reachable(), reason=HAPI_SKIP)
async def test_fhir_mode_get_patient_record(
    fhir_stdio_server_params: StdioServerParameters,
) -> None:
    async with stdio_client(fhir_stdio_server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "get_patient_record",
                {"patient_id": KNOWN_PATIENT_ID},
            )
    assert result.isError is False
    patient = Patient.model_validate(result.structuredContent)
    assert patient.id == KNOWN_PATIENT_ID


@pytest.mark.anyio
@pytest.mark.network
@pytest.mark.skipif(not _hapi_reachable(), reason=HAPI_SKIP)
async def test_fhir_mode_get_patient_observations_loinc(
    fhir_stdio_server_params: StdioServerParameters,
) -> None:
    async with stdio_client(fhir_stdio_server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "get_patient_observations",
                {"patient_id": LOINC_PATIENT_ID, "code": A1C_LOINC},
            )
    assert result.isError is False
    observations = [
        Observation.model_validate(item)
        for item in _tool_list_payload(result.structuredContent)
    ]
    assert observations
    for observation in observations:
        coding = observation.code.coding
        assert coding is not None
        assert any(
            c.system == "http://loinc.org" and c.code == "4548-4" for c in coding
        )


@pytest.mark.anyio
@pytest.mark.network
@pytest.mark.skipif(not _hapi_reachable(), reason=HAPI_SKIP)
async def test_fhir_mode_get_conditions_and_medications(
    fhir_stdio_server_params: StdioServerParameters,
) -> None:
    async with stdio_client(fhir_stdio_server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            conditions_result = await session.call_tool(
                "get_patient_conditions",
                {"patient_id": LOINC_PATIENT_ID},
            )
            medications_result = await session.call_tool(
                "get_patient_medications",
                {"patient_id": LOINC_PATIENT_ID},
            )
    assert conditions_result.isError is False
    assert medications_result.isError is False
    conditions = [
        Condition.model_validate(item)
        for item in _tool_list_payload(conditions_result.structuredContent)
    ]
    medications = [
        MedicationRequest.model_validate(item)
        for item in _tool_list_payload(medications_result.structuredContent)
    ]
    assert conditions
    assert medications
