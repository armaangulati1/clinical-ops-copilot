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
from servers.clinical_data.patients import get_patient_record as fetch_patient_record
from servers.clinical_data.patients import list_patient_ids
from servers.clinical_data.policy_service import get_payer_policy as lookup_payer_policy

mcp = FastMCP("clinical-data")
_config: ServerConfig = load_config()


def configure(config: ServerConfig) -> None:
    """Set runtime configuration for tools and resources."""
    global _config
    _config = config


def get_config() -> ServerConfig:
    return _config


@mcp.tool()
def get_patient_record(patient_id: str) -> dict[str, Any]:
    """Return a synthetic FHIR Patient resource by ID."""
    patient = fetch_patient_record(patient_id)
    return patient.model_dump(mode="json")


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
    """Expose a synthetic FHIR Patient via URI template."""
    return fetch_patient_record(patient_id).model_dump_json()


def register_static_patient_resources() -> None:
    """Register listable patient resources for each known patient ID."""
    for patient_id in list_patient_ids():

        def _make_resource(pid: str) -> None:
            @mcp.resource(f"patient://{pid}")
            def _read_patient() -> str:
                return fetch_patient_record(pid).model_dump_json()

        _make_resource(patient_id)


register_static_patient_resources()
