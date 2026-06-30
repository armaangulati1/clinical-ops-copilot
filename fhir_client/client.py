"""Typed read-only FHIR R4 client."""

from __future__ import annotations

from typing import Any, TypeVar

import httpx
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from fhir_client.bundle import next_page_url, resources_from_bundle
from fhir_client.config import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_PAGES,
    DEFAULT_PAGE_COUNT,
    DEFAULT_TIMEOUT_SECONDS,
    fhir_base_url,
)
from fhir_client.errors import FhirError, FhirNotFound, FhirTransientError
from fhir_client.models import Condition, MedicationRequest, Observation, Patient

T = TypeVar("T", bound=BaseModel)


class FhirClient:
    """Read-side FHIR client with retries, paging, and typed resources."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        page_count: int = DEFAULT_PAGE_COUNT,
        max_pages: int = DEFAULT_MAX_PAGES,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = (base_url or fhir_base_url()).rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_attempts = max_attempts
        self._page_count = page_count
        self._max_pages = max_pages
        self._http_client = http_client
        self._owns_client = http_client is None

    def close(self) -> None:
        if self._owns_client and self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def __enter__(self) -> FhirClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=self._timeout_seconds)
        return self._http_client

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, str] | None = None,
    ) -> httpx.Response:
        @retry(
            stop=stop_after_attempt(self._max_attempts),
            wait=wait_exponential(multiplier=1, min=1, max=8),
            retry=retry_if_exception_type(
                (FhirTransientError, httpx.TimeoutException, httpx.TransportError)
            ),
            reraise=True,
        )
        def _do_request() -> httpx.Response:
            try:
                if params is None:
                    response = self._client().request(method, url)
                else:
                    response = self._client().request(method, url, params=params)
            except httpx.TimeoutException as exc:
                raise FhirTransientError(
                    f"FHIR request timed out: {url}",
                    url=url,
                ) from exc
            except httpx.TransportError as exc:
                raise FhirTransientError(
                    f"FHIR transport error: {url}",
                    url=url,
                ) from exc
            self._raise_for_response(response, url=url)
            return response

        return _do_request()

    @staticmethod
    def _raise_for_response(response: httpx.Response, *, url: str) -> None:
        if response.status_code == 404:
            raise FhirNotFound(
                f"FHIR resource not found: {url}",
                status_code=404,
                url=url,
            )
        if response.status_code >= 500:
            raise FhirTransientError(
                f"FHIR server error {response.status_code}: {url}",
                status_code=response.status_code,
                url=url,
            )
        if response.status_code >= 400:
            detail = response.text[:300] if response.text else response.reason_phrase
            raise FhirError(
                f"FHIR client error {response.status_code}: {detail}",
                status_code=response.status_code,
                url=url,
            )

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self._base_url}/{path.lstrip('/')}"
        response = self._request("GET", url, params=params)
        payload = response.json()
        if not isinstance(payload, dict):
            msg = f"Expected JSON object from {url}"
            raise FhirError(msg, url=url)
        return payload

    def _search_resources(
        self,
        resource_type: str,
        params: dict[str, str],
        model: type[T],
    ) -> list[T]:
        page_params: dict[str, str] = dict(params)
        page_params.setdefault("_count", str(self._page_count))
        url = f"{self._base_url}/{resource_type}"
        items: list[T] = []
        request_params: dict[str, str] | None = page_params

        for _page in range(self._max_pages):
            payload = self._request("GET", url, params=request_params).json()
            if not isinstance(payload, dict):
                msg = f"Expected JSON object from {url}"
                raise FhirError(msg, url=url)
            items.extend(resources_from_bundle(payload, model))
            next_url = next_page_url(payload, base_url=self._base_url)
            if not next_url:
                break
            url = next_url
            request_params = None
        return items

    def get_patient(self, patient_id: str) -> Patient:
        payload = self._get_json(f"Patient/{patient_id}")
        return Patient.model_validate(payload)

    def list_patients(self) -> list[Patient]:
        """Return patients from an unpaginated-capable server search."""
        return self._search_resources("Patient", {}, Patient)

    def search_patients(self, **params: str) -> list[Patient]:
        if not params:
            msg = "search_patients requires at least one search parameter"
            raise ValueError(msg)
        return self._search_resources("Patient", params, Patient)

    def get_observations(
        self,
        patient_id: str,
        *,
        code: str | None = None,
    ) -> list[Observation]:
        query = {"patient": patient_id}
        if code is not None:
            query["code"] = code
        return self._search_resources("Observation", query, Observation)

    def get_conditions(self, patient_id: str) -> list[Condition]:
        return self._search_resources("Condition", {"patient": patient_id}, Condition)

    def get_medication_requests(self, patient_id: str) -> list[MedicationRequest]:
        return self._search_resources(
            "MedicationRequest",
            {"patient": patient_id},
            MedicationRequest,
        )

    def is_reachable(self) -> bool:
        """Return True when the server metadata endpoint responds."""
        try:
            self._get_json("metadata")
        except FhirError:
            return False
        else:
            return True
