"""Clinical-data MCP server (read side)."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from schemas.extraction_result import ExtractionResult
from schemas.policies import PayerPolicy
from servers.clinical_data.config import ServerConfig, load_config
from servers.clinical_data.extractor import extract
from servers.clinical_data.oncology_client import extract_oncology_note
from servers.clinical_data.oncology_schema import ExtractionOutput
from servers.clinical_data.path_security import (
    PathNotAccessibleError,
    assert_path_allowed,
)
from servers.clinical_data.patient_service import (
    get_patient_conditions as fetch_patient_conditions,
)
from servers.clinical_data.patient_service import (
    get_patient_medications as fetch_patient_medications,
)
from servers.clinical_data.patient_service import (
    get_patient_observations as fetch_patient_observations,
)
from servers.clinical_data.patient_service import (
    get_patient_record as fetch_patient_record,
)
from servers.clinical_data.patient_service import (
    list_patient_ids,
)
from servers.clinical_data.policy_service import get_payer_policy as lookup_payer_policy

mcp = FastMCP("clinical-data")
_config: ServerConfig = load_config()
_registered_patient_resources: set[str] = set()


def configure(config: ServerConfig) -> None:
    """Set runtime configuration for tools and resources."""
    global _config
    _config = config
    register_patient_resources()


def get_config() -> ServerConfig:
    return _config


@mcp.tool()
def get_patient_record(patient_id: str) -> dict[str, Any]:
    """Return a FHIR Patient resource by ID."""
    patient = fetch_patient_record(get_config(), patient_id)
    return patient.model_dump(mode="json")


@mcp.tool()
def get_patient_observations(
    patient_id: str,
    code: str | None = None,
) -> list[dict[str, Any]]:
    """Return FHIR Observations for a patient, optionally filtered by LOINC code."""
    return fetch_patient_observations(get_config(), patient_id, code=code)


@mcp.tool()
def get_patient_conditions(patient_id: str) -> list[dict[str, Any]]:
    """Return FHIR Conditions for a patient."""
    return fetch_patient_conditions(get_config(), patient_id)


@mcp.tool()
def get_patient_medications(patient_id: str) -> list[dict[str, Any]]:
    """Return FHIR MedicationRequests for a patient."""
    return fetch_patient_medications(get_config(), patient_id)


@mcp.tool()
def get_payer_policy(drug: str, condition: str) -> PayerPolicy:
    """Return payer prior-auth criteria for a drug and condition."""
    return lookup_payer_policy(drug, condition)


@mcp.tool()
def extract_chart(
    note_text: str | None = None,
    chart_path: str | None = None,
    drug: str | None = None,
    condition: str | None = None,
) -> ExtractionResult:
    """Extract prior-auth fields with per-field confidence metadata."""
    if note_text and chart_path:
        msg = "Provide only one of note_text or chart_path"
        raise ValueError(msg)
    if not note_text and not chart_path:
        msg = "Provide note_text or chart_path"
        raise ValueError(msg)

    if chart_path is not None:
        try:
            allowed_path = assert_path_allowed(chart_path, get_config().chart_roots)
        except PathNotAccessibleError:
            raise
        note_text = allowed_path.read_text(encoding="utf-8")

    assert note_text is not None
    policy = lookup_payer_policy(drug, condition) if drug and condition else None
    return extract(note_text, policy=policy)


@mcp.tool()
def extract_oncology_chart(
    note_text: str,
    review_threshold: float | None = None,
) -> ExtractionOutput:
    """Extract oncology variables via the ChartExtractor API.

    This uses ChartExtractor's OncologyExtract schema, not prior-auth Extraction.
    """
    return extract_oncology_note(note_text, review_threshold=review_threshold)


@mcp.resource("patient://{patient_id}")
def patient_resource(patient_id: str) -> str:
    """Expose a FHIR Patient via URI template."""
    return fetch_patient_record(get_config(), patient_id).model_dump_json()


def register_patient_resources() -> None:
    """Register listable patient resources for the active data source."""
    for patient_id in list_patient_ids(get_config()):
        if patient_id in _registered_patient_resources:
            continue
        _registered_patient_resources.add(patient_id)

        def _make_resource(pid: str) -> None:
            @mcp.resource(f"patient://{pid}")
            def _read_patient() -> str:
                return fetch_patient_record(get_config(), pid).model_dump_json()

        _make_resource(patient_id)


configure(load_config())
