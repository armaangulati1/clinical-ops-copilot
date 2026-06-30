"""Patient data access for mock and FHIR-backed clinical-data modes."""

from __future__ import annotations

from typing import Any

from fhir_client.client import FhirClient
from fhir_client.errors import FhirNotFound
from fhir_client.models import Patient
from servers.clinical_data.config import ServerConfig
from servers.clinical_data.patients import get_patient_record as mock_get_patient_record
from servers.clinical_data.patients import list_patient_ids as mock_list_patient_ids

_fhir_client_override: FhirClient | None = None


def set_fhir_client_override(client: FhirClient | None) -> None:
    """Inject a FHIR client for tests (None resets to default factory)."""
    global _fhir_client_override
    _fhir_client_override = client


def _fhir_client() -> FhirClient:
    if _fhir_client_override is not None:
        return _fhir_client_override
    return FhirClient()


def _serialize_resources(resources: list[Any]) -> list[dict[str, Any]]:
    return [resource.model_dump(mode="json") for resource in resources]


def get_patient_record(config: ServerConfig, patient_id: str) -> Patient:
    if config.data_source == "mock":
        return Patient.model_validate(
            mock_get_patient_record(patient_id).model_dump(mode="json")
        )
    try:
        return _fhir_client().get_patient(patient_id)
    except FhirNotFound as exc:
        msg = f"Unknown patient_id: {patient_id}"
        raise ValueError(msg) from exc


def list_patient_ids(config: ServerConfig) -> list[str]:
    if config.data_source == "mock":
        return mock_list_patient_ids()
    patients = _fhir_client().list_patients()
    ids = [patient.id for patient in patients if patient.id]
    return sorted(set(ids))


def get_patient_observations(
    config: ServerConfig,
    patient_id: str,
    *,
    code: str | None = None,
) -> list[dict[str, Any]]:
    if config.data_source == "mock":
        return []
    observations = _fhir_client().get_observations(patient_id, code=code)
    return _serialize_resources(observations)


def get_patient_conditions(
    config: ServerConfig,
    patient_id: str,
) -> list[dict[str, Any]]:
    if config.data_source == "mock":
        return []
    conditions = _fhir_client().get_conditions(patient_id)
    return _serialize_resources(conditions)


def get_patient_medications(
    config: ServerConfig,
    patient_id: str,
) -> list[dict[str, Any]]:
    if config.data_source == "mock":
        return []
    medications = _fhir_client().get_medication_requests(patient_id)
    return _serialize_resources(medications)
