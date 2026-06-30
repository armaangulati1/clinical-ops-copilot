"""Redact PHI from FHIR resources before logging or audit persistence."""

from __future__ import annotations

from typing import Any

from schemas.phi_redaction import (
    TOKEN_ADDRESS,
    TOKEN_DOB,
    TOKEN_FREE_TEXT,
    TOKEN_MRN,
    TOKEN_NAME,
    TOKEN_PHONE,
    redact_text,
)

FHIR_PHI_OBJECT_FIELDS = frozenset(
    {"name", "identifier", "address", "telecom", "contact", "managingOrganization"}
)
FHIR_STRIP_CONTENT_FIELDS = frozenset({"note"})


def redact_fhir_for_logging(value: Any) -> Any:
    """Recursively redact PHI from FHIR JSON suitable for logs and audit."""
    if isinstance(value, list):
        return [redact_fhir_for_logging(item) for item in value]
    if isinstance(value, dict):
        if value.get("resourceType") == "Patient":
            return _redact_patient_resource(value)
        if _looks_like_human_name(value):
            return {"text": TOKEN_NAME}
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            if key in FHIR_STRIP_CONTENT_FIELDS:
                redacted[key] = _redact_fhir_free_text_field(nested)
            elif key in FHIR_PHI_OBJECT_FIELDS:
                redacted[key] = _redact_fhir_phi_field(key, nested)
            elif key == "birthDate" and isinstance(nested, str):
                redacted[key] = TOKEN_DOB
            elif key == "display" and isinstance(nested, str):
                redacted[key] = redact_text(nested)
            else:
                redacted[key] = redact_fhir_for_logging(nested)
        return redacted
    if isinstance(value, str):
        return redact_text(value)
    return value


def _redact_patient_resource(patient: dict[str, Any]) -> dict[str, Any]:
    redacted = redact_fhir_for_logging(
        {key: value for key, value in patient.items() if key != "resourceType"}
    )
    if not isinstance(redacted, dict):
        redacted = {}
    redacted["resourceType"] = "Patient"
    if "name" in patient:
        redacted["name"] = [{"text": TOKEN_NAME}]
    if "identifier" in patient:
        redacted["identifier"] = [{"value": TOKEN_MRN}]
    if "birthDate" in patient:
        redacted["birthDate"] = TOKEN_DOB
    if "address" in patient:
        redacted["address"] = [{"text": TOKEN_ADDRESS}]
    if "telecom" in patient:
        redacted["telecom"] = [{"value": TOKEN_PHONE}]
    return redacted


def _redact_fhir_phi_field(field_name: str, value: Any) -> Any:
    if field_name == "name":
        return [{"text": TOKEN_NAME}]
    if field_name == "identifier":
        return [{"value": TOKEN_MRN}]
    if field_name == "address":
        return [{"text": TOKEN_ADDRESS}]
    if field_name == "telecom":
        return [{"value": TOKEN_PHONE}]
    return TOKEN_NAME


def _redact_fhir_free_text_field(value: Any) -> Any:
    if isinstance(value, list):
        return [{"text": TOKEN_FREE_TEXT}]
    if isinstance(value, dict):
        return {"text": TOKEN_FREE_TEXT}
    if isinstance(value, str):
        return TOKEN_FREE_TEXT
    return TOKEN_FREE_TEXT


def _looks_like_human_name(value: dict[str, Any]) -> bool:
    return "family" in value or "given" in value
