"""HL7 v2.x ingestion layer (ADT^A01 + ORU^R01 subset, demo scope).

A hand-rolled, dependency-free HL7 v2 parser plus mappers onto the copilot's
existing ingestion boundaries: ADT^A01 -> patient context (the
``Case.patient_id`` identity boundary), ORU^R01 ->
``agent.fhir_facts.FhirClinicalBundle`` (the structured-observation boundary the
unchanged fact resolver consumes). Synthetic data only; not a certified HL7
interface engine. See hl7v2/README.md for the supported segment subset and the
two mapping boundaries.
"""

from __future__ import annotations

from hl7v2.errors import (
    EmptyMessageError,
    HL7ParseError,
    InvalidDelimiterError,
    InvalidSegmentError,
    MissingSegmentError,
    UnsupportedMessageTypeError,
    UnsupportedVersionError,
)
from hl7v2.mapper import (
    MappedBundle,
    PatientContext,
    map_adt,
    map_oru,
)
from hl7v2.parser import (
    Delimiters,
    HL7Message,
    MSHHeader,
    ObservationRequest,
    ObservationResult,
    PatientIdentification,
    PatientIdentifier,
    PatientVisit,
    Segment,
    detect_delimiters,
    parse_message,
    tokenize,
)

__all__ = [
    "Delimiters",
    "EmptyMessageError",
    "HL7Message",
    "HL7ParseError",
    "InvalidDelimiterError",
    "InvalidSegmentError",
    "MSHHeader",
    "MappedBundle",
    "MissingSegmentError",
    "ObservationRequest",
    "ObservationResult",
    "PatientContext",
    "PatientIdentification",
    "PatientIdentifier",
    "PatientVisit",
    "Segment",
    "UnsupportedMessageTypeError",
    "UnsupportedVersionError",
    "detect_delimiters",
    "map_adt",
    "map_oru",
    "parse_message",
    "tokenize",
]
