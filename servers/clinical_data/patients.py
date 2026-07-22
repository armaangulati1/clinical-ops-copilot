"""Synthetic FHIR patient records for the clinical-data server."""

from __future__ import annotations

from fhir.resources.patient import Patient

PATIENT_RECORDS: dict[str, Patient] = {
    "patient-001": Patient.model_validate(
        {
            "resourceType": "Patient",
            "id": "patient-001",
            "active": True,
            "name": [{"use": "official", "family": "Blake", "given": ["Jordan"]}],
            "gender": "female",
            "birthDate": "1973-04-12",
        },
    ),
    "patient-002": Patient.model_validate(
        {
            "resourceType": "Patient",
            "id": "patient-002",
            "active": True,
            "name": [{"use": "official", "family": "Chen", "given": ["Avery"]}],
            "gender": "male",
            "birthDate": "1964-08-03",
        },
    ),
    "patient-003": Patient.model_validate(
        {
            "resourceType": "Patient",
            "id": "patient-003",
            "active": True,
            "name": [{"use": "official", "family": "Bell", "given": ["Nova"]}],
            "gender": "female",
            "birthDate": "1987-11-21",
        },
    ),
}


def get_patient_record(patient_id: str) -> Patient:
    """Return a validated FHIR Patient resource.

    Records in ``PATIENT_RECORDS`` are already validated once, at import, via
    ``Patient.model_validate``. The previous implementation re-validated on every
    call (``model_validate(patient.model_dump(mode="json"))``), running the full
    FHIR validation pass per request for no correctness gain. ``model_copy`` with
    ``deep=True`` hands callers an isolated copy, so they still cannot mutate the
    shared record, without re-running the validators.
    """
    if patient_id not in PATIENT_RECORDS:
        msg = f"Unknown patient_id: {patient_id}"
        raise ValueError(msg)
    return PATIENT_RECORDS[patient_id].model_copy(deep=True)


def list_patient_ids() -> list[str]:
    """Return known synthetic patient identifiers."""
    return sorted(PATIENT_RECORDS.keys())


def patient_display_name(patient_id: str) -> str:
    patient = get_patient_record(patient_id)
    if not patient.name:
        return patient_id
    name = patient.name[0]
    given = " ".join(value for value in (name.given or []) if value)
    family = name.family or ""
    return f"{given} {family}".strip()
