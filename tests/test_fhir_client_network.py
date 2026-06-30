"""Network integration tests against local HAPI FHIR."""

from __future__ import annotations

import os

import pytest

from fhir_client.client import FhirClient
from fhir_client.config import DEFAULT_FHIR_BASE_URL, FHIR_BASE_URL_ENV
from fhir_client.models import Condition, MedicationRequest, Observation, Patient

KNOWN_PATIENT_ID = "1122"
LOINC_PATIENT_ID = "1652"
A1C_LOINC = "http://loinc.org|4548-4"
HAPI_SKIP = "local HAPI FHIR server not reachable"


def _fhir_base_url() -> str:
    return os.environ.get(FHIR_BASE_URL_ENV, DEFAULT_FHIR_BASE_URL).rstrip("/")


def _hapi_reachable() -> bool:
    with FhirClient(base_url=_fhir_base_url()) as client:
        return client.is_reachable()


@pytest.mark.network
@pytest.mark.skipif(not _hapi_reachable(), reason=HAPI_SKIP)
def test_get_patient_known_synthea_patient() -> None:
    with FhirClient(base_url=_fhir_base_url()) as client:
        patient = client.get_patient(KNOWN_PATIENT_ID)
    assert isinstance(patient, Patient)
    assert patient.id == KNOWN_PATIENT_ID
    assert patient.gender == "female"


@pytest.mark.network
@pytest.mark.skipif(not _hapi_reachable(), reason=HAPI_SKIP)
def test_search_patients_by_gender_returns_results() -> None:
    with FhirClient(base_url=_fhir_base_url()) as client:
        patients = client.search_patients(gender="female")
    assert patients
    assert all(isinstance(p, Patient) for p in patients)
    assert any(p.id == KNOWN_PATIENT_ID for p in patients)


@pytest.mark.network
@pytest.mark.skipif(not _hapi_reachable(), reason=HAPI_SKIP)
def test_get_observations_loinc_code_filters_results() -> None:
    with FhirClient(base_url=_fhir_base_url()) as client:
        observations = client.get_observations(LOINC_PATIENT_ID, code=A1C_LOINC)
    assert observations
    assert all(isinstance(o, Observation) for o in observations)
    for observation in observations:
        coding = observation.code.coding
        assert coding is not None
        assert any(
            c.system == "http://loinc.org" and c.code == "4548-4" for c in coding
        )


@pytest.mark.network
@pytest.mark.skipif(not _hapi_reachable(), reason=HAPI_SKIP)
def test_get_conditions_and_medication_requests_non_empty() -> None:
    with FhirClient(base_url=_fhir_base_url()) as client:
        conditions = client.get_conditions(LOINC_PATIENT_ID)
        medications = client.get_medication_requests(LOINC_PATIENT_ID)
    assert conditions
    assert medications
    assert all(isinstance(c, Condition) for c in conditions)
    assert all(isinstance(m, MedicationRequest) for m in medications)
