"""Unit tests for clinical-data patient service (mock mode)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fhir_client.models import Patient
from servers.clinical_data.config import ServerConfig
from servers.clinical_data.patient_service import (
    get_patient_conditions,
    get_patient_medications,
    get_patient_observations,
    get_patient_record,
    list_patient_ids,
)


@pytest.fixture
def mock_config(tmp_path: Path) -> ServerConfig:
    return ServerConfig(chart_roots=(tmp_path,), data_source="mock")


def test_mock_get_patient_record_returns_known_patient(
    mock_config: ServerConfig,
) -> None:
    patient = get_patient_record(mock_config, "patient-001")
    assert isinstance(patient, Patient)
    assert patient.id == "patient-001"


def test_mock_get_patient_record_unknown_raises(mock_config: ServerConfig) -> None:
    with pytest.raises(ValueError, match="Unknown patient_id"):
        get_patient_record(mock_config, "missing")


def test_mock_new_tools_return_empty_lists(mock_config: ServerConfig) -> None:
    assert get_patient_observations(mock_config, "patient-001") == []
    assert get_patient_conditions(mock_config, "patient-001") == []
    assert get_patient_medications(mock_config, "patient-001") == []


def test_mock_list_patient_ids(mock_config: ServerConfig) -> None:
    assert list_patient_ids(mock_config) == [
        "patient-001",
        "patient-002",
        "patient-003",
    ]
