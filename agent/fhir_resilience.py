"""Graceful degradation when the FHIR server is unreachable."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from fhir_client.errors import FhirTransientError

logger = logging.getLogger(__name__)

FHIR_UNAVAILABLE_FALLBACK_REASON = "fhir_server_unavailable"
FHIR_UNAVAILABLE_WARNING_TEMPLATE = (
    "FHIR server unavailable after retries; falling back to note-only "
    "extraction for case %s"
)

_UNAVAILABLE_MESSAGE_MARKERS = (
    "fhir",
    "transport",
    "connection",
    "timed out",
    "timeout",
    "unreachable",
    "refused",
    "connect",
)


def is_fhir_unavailable_error(exc: BaseException) -> bool:
    """Return True when an exception indicates FHIR is unreachable."""
    if isinstance(
        exc,
        (
            FhirTransientError,
            httpx.TransportError,
            httpx.TimeoutException,
            ConnectionError,
            OSError,
        ),
    ):
        return True
    if isinstance(exc, RuntimeError):
        message = str(exc).lower()
        return any(marker in message for marker in _UNAVAILABLE_MESSAGE_MARKERS)
    cause = exc.__cause__
    if cause is not None and cause is not exc:
        return is_fhir_unavailable_error(cause)
    return False


def log_fhir_unavailable_fallback(*, case_id: str, error: BaseException) -> None:
    """Emit an intentional, documented WARNING for note-only fallback."""
    logger.warning(
        FHIR_UNAVAILABLE_WARNING_TEMPLATE,
        case_id,
        exc_info=error,
    )


def fhir_fallback_audit_payload(error: BaseException) -> dict[str, Any]:
    """Structured audit payload for FHIR degradation events."""
    return {
        "reason": FHIR_UNAVAILABLE_FALLBACK_REASON,
        "message": FHIR_UNAVAILABLE_WARNING_TEMPLATE.replace("%s", "[CASE]"),
        "error_type": type(error).__name__,
        "error_summary": redact_error_summary(str(error)),
    }


def redact_error_summary(message: str) -> str:
    """Keep error summaries short and free of connection secrets."""
    trimmed = message.strip().replace("\n", " ")
    if len(trimmed) > 240:
        return trimmed[:237] + "..."
    return trimmed
