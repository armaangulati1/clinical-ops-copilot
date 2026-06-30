"""Unit tests for config-driven FHIR fact resolution (offline)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from agent.fhir_facts import (
    A1C_LOINC,
    BMI_LOINC,
    T2D_FHIR_MAPPING,
    FhirClinicalBundle,
    fuse_extraction_with_fhir,
    resolve_fhir_facts,
)
from schemas.extraction import Extraction
from schemas.extraction_result import ExtractionResult

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "tests/fixtures/fhir_patient_78748.json"
REFERENCE_DATE = datetime(2026, 6, 29, tzinfo=UTC)


def _load_fixture_bundle() -> FhirClinicalBundle:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return FhirClinicalBundle(
        observations_by_loinc=payload["observations"],
        conditions=payload["conditions"],
        medications=payload["medications"],
        reference_date=REFERENCE_DATE,
    )


def test_resolve_t2d_facts_uses_most_recent_a1c_with_provenance() -> None:
    bundle = _load_fixture_bundle()
    facts = resolve_fhir_facts(T2D_FHIR_MAPPING, bundle)

    a1c = facts["a1c_percent"]
    assert a1c.value == 6.72
    assert a1c.provenance == "FHIR Observation 4548-4, effective 2026-03-03"


def test_resolve_t2d_facts_resolves_bmi_condition_and_metformin_trial() -> None:
    bundle = _load_fixture_bundle()
    facts = resolve_fhir_facts(T2D_FHIR_MAPPING, bundle)

    assert facts["bmi"].value == 32.86
    assert "FHIR Observation 39156-5" in facts["bmi"].provenance

    assert facts["diabetes_duration_years"].value == 3
    assert (
        "FHIR Condition Diabetes mellitus type 2"
        in facts["diabetes_duration_years"].provenance
    )
    assert "onset 2023-01-17" in facts["diabetes_duration_years"].provenance

    assert facts["metformin_trial_months"].value >= 38
    assert "FHIR MedicationRequest" in facts["metformin_trial_months"].provenance
    assert "metformin" in facts["metformin_trial_months"].provenance.lower()


def test_fuse_prefers_fhir_over_note_for_required_fields() -> None:
    bundle = _load_fixture_bundle()
    fhir_facts = resolve_fhir_facts(T2D_FHIR_MAPPING, bundle)
    note = ExtractionResult(
        extraction=Extraction(a1c_percent=9.9, bmi=25.0),
        field_confidence={"a1c_percent": 0.6, "bmi": 0.6},
        needs_review=["a1c_percent", "bmi"],
        evidence={"a1c_percent": "note snippet", "bmi": "note snippet"},
    )

    fused = fuse_extraction_with_fhir(
        note,
        fhir_facts,
        required_fields=["a1c_percent", "bmi", "metformin_trial_months"],
    )

    assert fused.extraction.a1c_percent == 6.72
    assert fused.extraction.bmi == 32.86
    assert fused.field_provenance["a1c_percent"].startswith("FHIR Observation 4548-4")
    assert "a1c_percent" not in fused.needs_review


def test_mapping_includes_diabetes_loinc_codes() -> None:
    loincs = {spec.loinc for spec in T2D_FHIR_MAPPING.observations}
    assert A1C_LOINC in loincs
    assert BMI_LOINC in loincs
