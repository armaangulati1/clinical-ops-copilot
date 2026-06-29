"""Offline unit tests for the typed FHIR client."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from fhir_client.bundle import next_page_url, resources_from_bundle
from fhir_client.client import FhirClient
from fhir_client.errors import FhirError, FhirNotFound, FhirTransientError
from fhir_client.models import Observation, Patient

FIXTURES = Path(__file__).parent / "fixtures" / "fhir"


def _load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_resources_from_bundle_parses_patients() -> None:
    patients = resources_from_bundle(_load_fixture("patient_searchset.json"), Patient)
    assert len(patients) == 2
    assert patients[0].id == "p-1"
    assert patients[1].name is not None
    assert patients[1].name[0].family == "Beta"


def test_resources_from_bundle_empty_entry_returns_empty_list() -> None:
    payload = {"resourceType": "Bundle", "type": "searchset", "entry": []}
    assert resources_from_bundle(payload, Patient) == []


def test_next_page_url_returns_absolute_next_link() -> None:
    payload = {
        "resourceType": "Bundle",
        "type": "searchset",
        "link": [
            {"relation": "self", "url": "http://localhost:8080/fhir/Patient?_count=1"},
            {
                "relation": "next",
                "url": "http://localhost:8080/fhir/Patient?_count=1&page=2",
            },
        ],
    }
    assert (
        next_page_url(payload, base_url="http://localhost:8080/fhir")
        == "http://localhost:8080/fhir/Patient?_count=1&page=2"
    )


def test_get_patient_maps_404_to_fhir_not_found() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, text="not found")

    client = FhirClient(
        base_url="http://example.test/fhir",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=3,
    )
    with pytest.raises(FhirNotFound):
        client.get_patient("missing")
    assert calls == 1


def test_request_retries_transient_5xx_then_succeeds() -> None:
    calls = 0
    patient_json = _load_fixture("patient_resource.json")

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json=patient_json)

    client = FhirClient(
        base_url="http://example.test/fhir",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=3,
    )
    patient = client.get_patient("p-1")
    assert patient.id == "p-1"
    assert calls == 3


def test_request_does_not_retry_on_400() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, text="bad request")

    client = FhirClient(
        base_url="http://example.test/fhir",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=3,
    )
    with pytest.raises(FhirError) as exc_info:
        client.get_patient("bad")
    assert exc_info.value.status_code == 400
    assert calls == 1


def test_search_patients_follows_next_link() -> None:
    page1 = _load_fixture("patient_searchset.json")
    page2 = {
        "resourceType": "Bundle",
        "type": "searchset",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": "p-3",
                    "name": [{"family": "Gamma", "given": ["Gina"]}],
                }
            }
        ],
        "link": [
            {"relation": "self", "url": "http://example.test/fhir/Patient?page=2"}
        ],
    }
    requests: list[str] = []
    page = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal page
        page += 1
        requests.append(str(request.url))
        if page == 1:
            return httpx.Response(
                200,
                json={
                    **page1,
                    "link": [
                        {
                            "relation": "next",
                            "url": "http://example.test/fhir/Patient?page=2",
                        }
                    ],
                },
            )
        return httpx.Response(200, json=page2)

    client = FhirClient(
        base_url="http://example.test/fhir",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    patients = client.search_patients(gender="female")
    assert [p.id for p in patients] == ["p-1", "p-2", "p-3"]
    assert len(requests) == 2


def test_get_observations_empty_searchset_returns_empty_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"resourceType": "Bundle", "type": "searchset", "total": 0},
        )

    client = FhirClient(
        base_url="http://example.test/fhir",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert client.get_observations("1652", code="http://loinc.org|4548-4") == []


def test_get_observations_parses_loinc_observation_fixture() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["code"] == "http://loinc.org|4548-4"
        return httpx.Response(200, json=_load_fixture("observation_searchset.json"))

    client = FhirClient(
        base_url="http://example.test/fhir",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    observations = client.get_observations("1652", code="http://loinc.org|4548-4")
    assert len(observations) == 1
    assert isinstance(observations[0], Observation)
    coding = observations[0].code.coding[0]
    assert coding.system == "http://loinc.org"
    assert coding.code == "4548-4"


def test_transient_error_is_subclass_of_fhir_error() -> None:
    assert issubclass(FhirTransientError, FhirError)
    assert issubclass(FhirNotFound, FhirError)
