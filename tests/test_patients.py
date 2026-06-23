"""Tests for synthetic FHIR patient records."""

from fhir.resources.patient import Patient

from servers.clinical_data.patients import get_patient_record


def test_get_patient_record_validates_with_fhir_resources() -> None:
    payload = get_patient_record("patient-001").model_dump(mode="json")
    patient = Patient.model_validate(payload)
    assert patient.id == "patient-001"
    assert patient.name is not None
    assert patient.name[0].family == "Blake"
