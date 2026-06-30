"""FHIR client exceptions."""

from __future__ import annotations


class FhirError(Exception):
    """Non-retryable FHIR client error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url


class FhirNotFound(FhirError):
    """Requested FHIR resource was not found (HTTP 404)."""


class FhirTransientError(FhirError):
    """Transient server or transport error eligible for retry."""
