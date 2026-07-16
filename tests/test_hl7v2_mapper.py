"""Tests for the HL7 v2 -> copilot boundary mappers.

Includes the load-bearing integration test: an ORU^R01 mapped to a
``FhirClinicalBundle`` resolves prior-auth observation fields through the
UNCHANGED ``agent.fhir_facts.resolve_fhir_facts``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.fhir_facts import (
    A1C_LOINC,
    BMI_LOINC,
    T2D_FHIR_MAPPING,
    resolve_fhir_facts,
)
from hl7v2.errors import UnsupportedMessageTypeError
from hl7v2.mapper import map_adt, map_oru
from hl7v2.parser import HL7Message, parse_message

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT_ROOT / "hl7v2" / "fixtures"


def _parse(name: str) -> HL7Message:
    return parse_message((FIXTURES / f"{name}.hl7").read_text(encoding="utf-8"))


def test_map_adt_fills_patient_id_boundary() -> None:
    context = map_adt(_parse("adt_a01_admit_basic"))
    # patient_id mirrors schemas.cases.Case.patient_id (the fusion identity key).
    assert context.patient_id == "MRN-0000123"
    assert context.family_name == "HOLLOWAY"
    assert context.birth_date == "1985-03-12"
    assert context.admit_datetime == "2027-01-15T14:30:00+00:00"
    assert context.patient_class == "I"


def test_map_oru_builds_loinc_keyed_bundle() -> None:
    bundle = map_oru(_parse("oru_r01_a1c_bmi")).bundle
    assert set(bundle.observations_by_loinc) == {A1C_LOINC, BMI_LOINC}
    a1c = bundle.observations_by_loinc[A1C_LOINC][0]
    assert a1c["resourceType"] == "Observation"
    assert a1c["status"] == "final"
    assert a1c["valueQuantity"]["value"] == 8.1
    assert a1c["effectiveDateTime"] == "2027-01-12T10:15:00+00:00"


def test_mapped_oru_resolves_facts_through_unchanged_resolver() -> None:
    """End-to-end: HL7 v2 -> bundle -> the repo's own fact resolver, untouched."""
    bundle = map_oru(_parse("oru_r01_a1c_bmi")).bundle
    facts = resolve_fhir_facts(T2D_FHIR_MAPPING, bundle)
    assert facts["a1c_percent"].value == 8.1
    assert facts["bmi"].value == 34.2
    assert facts["a1c_percent"].provenance.startswith("FHIR Observation 4548-4")


def test_string_obx_becomes_value_string() -> None:
    bundle = map_oru(_parse("oru_r01_mixed_types")).bundle
    string_obs = bundle.observations_by_loinc["http://loinc.org|600-7"][0]
    assert string_obs["valueString"] == "No growth after 48 hours"
    assert "valueQuantity" not in string_obs


def test_map_adt_rejects_oru() -> None:
    with pytest.raises(UnsupportedMessageTypeError):
        map_adt(_parse("oru_r01_a1c_bmi"))


def test_map_oru_rejects_adt() -> None:
    with pytest.raises(UnsupportedMessageTypeError):
        map_oru(_parse("adt_a01_admit_basic"))
