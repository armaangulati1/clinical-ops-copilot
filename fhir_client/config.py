"""FHIR client configuration."""

from __future__ import annotations

import os

DEFAULT_FHIR_BASE_URL = "http://localhost:8080/fhir"
FHIR_BASE_URL_ENV = "FHIR_BASE_URL"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_PAGE_COUNT = 100
DEFAULT_MAX_PAGES = 50
DEFAULT_MAX_ATTEMPTS = 3


def fhir_base_url() -> str:
    return os.environ.get(FHIR_BASE_URL_ENV, DEFAULT_FHIR_BASE_URL).rstrip("/")
