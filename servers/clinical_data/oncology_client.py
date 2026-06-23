"""HTTP client for the deployed ChartExtractor oncology API."""

from __future__ import annotations

import os

import httpx
from pydantic import ValidationError

from servers.clinical_data.oncology_schema import ExtractionOutput

DEFAULT_API_URL = "https://chartextract.onrender.com"
API_URL_ENV = "CHARTEXTRACT_API_URL"
DEFAULT_TIMEOUT_SECONDS = 90.0
MAX_ATTEMPTS = 3


class ChartExtractAPIError(RuntimeError):
    """Raised when the ChartExtractor API cannot be reached or returns an error."""


def _api_base_url() -> str:
    return os.environ.get(API_URL_ENV, DEFAULT_API_URL).rstrip("/")


def extract_oncology_note(
    note_text: str,
    *,
    review_threshold: float | None = None,
    base_url: str | None = None,
    http_client: httpx.Client | None = None,
) -> ExtractionOutput:
    """Call ChartExtractor ``POST /extract`` and validate the response."""
    url = f"{(base_url or _api_base_url())}/extract"
    payload: dict[str, object] = {"text": note_text}
    if review_threshold is not None:
        payload["review_threshold"] = review_threshold

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if http_client is not None:
                response = http_client.post(url, json=payload)
            else:
                with httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS) as client:
                    response = client.post(url, json=payload)
            response.raise_for_status()
            return ExtractionOutput.model_validate(response.json())
        except (
            httpx.HTTPStatusError,
            httpx.TimeoutException,
            httpx.TransportError,
        ) as exc:
            last_error = exc
            if attempt == MAX_ATTEMPTS:
                break
        except ValidationError as exc:
            raise ChartExtractAPIError(
                "ChartExtractor API returned an invalid response payload"
            ) from exc

    msg = f"ChartExtractor API request failed after {MAX_ATTEMPTS} attempts"
    raise ChartExtractAPIError(msg) from last_error
