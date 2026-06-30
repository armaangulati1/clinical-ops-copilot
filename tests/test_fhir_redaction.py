"""Unit tests for FHIR PHI redaction before logging."""

from __future__ import annotations

from schemas.fhir_redaction import redact_fhir_for_logging
from schemas.phi_redaction import (
    TOKEN_ADDRESS,
    TOKEN_DOB,
    TOKEN_MRN,
    TOKEN_NAME,
    TOKEN_PHONE,
)


def seed_patient_resource() -> dict[str, object]:
    return {
        "resourceType": "Patient",
        "id": "phi-seed-1",
        "name": [{"family": "Carter", "given": ["Evelyn"], "text": "Evelyn Carter"}],
        "birthDate": "1975-03-14",
        "identifier": [
            {
                "system": "http://hospital.example/mrn",
                "value": "MRN-8827441",
            }
        ],
        "address": [
            {
                "line": ["742 Evergreen Terrace"],
                "city": "Springfield",
                "state": "IL",
            }
        ],
        "telecom": [{"system": "phone", "value": "(415) 555-0192"}],
    }


def test_redact_fhir_patient_masks_identifiers() -> None:
    redacted = redact_fhir_for_logging(seed_patient_resource())
    assert isinstance(redacted, dict)
    serialized = str(redacted)
    assert "Evelyn Carter" not in serialized
    assert "MRN-8827441" not in serialized
    assert "1975-03-14" not in serialized
    assert "742 Evergreen Terrace" not in serialized
    assert "(415) 555-0192" not in serialized
    assert TOKEN_NAME in serialized
    assert TOKEN_MRN in serialized
    assert TOKEN_DOB in serialized
    assert TOKEN_ADDRESS in serialized
    assert TOKEN_PHONE in serialized
