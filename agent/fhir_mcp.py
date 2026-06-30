"""Fetch structured FHIR clinical data via clinical-data MCP tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agent.config import CLINICAL_DATA_SERVER
from agent.fhir_facts import FhirClinicalBundle, PolicyFhirMapping
from agent.mcp_host import qualify_tool


def unwrap_fhir_list(payload: Any) -> list[dict[str, Any]]:
    """Normalize MCP list tool payloads (bare list or {\"result\": [...]})."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, list):
            return [item for item in result if isinstance(item, dict)]
    return []


async def fetch_fhir_bundle(
    patient_id: str,
    mapping: PolicyFhirMapping,
    *,
    call_tool: Callable[[str, dict[str, Any]], Awaitable[Any]],
) -> FhirClinicalBundle:
    """Load observations, conditions, and medications for fact resolution."""
    observations_by_loinc: dict[str, list[dict[str, Any]]] = {}
    for spec in mapping.observations:
        payload = await call_tool(
            qualify_tool(CLINICAL_DATA_SERVER, "get_patient_observations"),
            {"patient_id": patient_id, "code": spec.loinc},
        )
        observations_by_loinc[spec.loinc] = unwrap_fhir_list(payload)

    conditions_payload = await call_tool(
        qualify_tool(CLINICAL_DATA_SERVER, "get_patient_conditions"),
        {"patient_id": patient_id},
    )
    medications_payload = await call_tool(
        qualify_tool(CLINICAL_DATA_SERVER, "get_patient_medications"),
        {"patient_id": patient_id},
    )
    return FhirClinicalBundle(
        observations_by_loinc=observations_by_loinc,
        conditions=unwrap_fhir_list(conditions_payload),
        medications=unwrap_fhir_list(medications_payload),
    )
