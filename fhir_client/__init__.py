"""Typed FHIR read client for HAPI and other FHIR R4 servers."""

from fhir_client.client import FhirClient
from fhir_client.errors import FhirError, FhirNotFound, FhirTransientError

__all__ = [
    "FhirClient",
    "FhirError",
    "FhirNotFound",
    "FhirTransientError",
]
