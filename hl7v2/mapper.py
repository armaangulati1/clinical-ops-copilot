"""Map parsed HL7 v2 messages onto the copilot's existing ingestion boundaries.

The agent decision path is byte-untouched. This module only translates a
parsed :class:`~hl7v2.parser.HL7Message` into structures the copilot already
consumes, mirroring how the X12 278 and FHIR layers feed it:

* ``ADT^A01`` -> :class:`PatientContext`. Its ``patient_id`` is the same
  identity key ``schemas.cases.Case.patient_id`` carries (the 278 layer fills
  that field from ``NM1*IL``; this fills it from ``PID-3``), so an admit
  message can seed the patient identity a case is later fused against.
* ``ORU^R01`` -> :class:`agent.fhir_facts.FhirClinicalBundle`. Each OBX becomes
  a FHIR R4B-shaped ``Observation`` resource keyed by ``system|code``, exactly
  the ``observations_by_loinc`` structure that the UNCHANGED
  ``agent.fhir_facts.resolve_fhir_facts`` consumes. A LOINC-coded ORU therefore
  resolves prior-auth observation fields (e.g. A1c, BMI) through the existing
  fact resolver with no change to that code.

Deterministic and offline. Synthetic self-authored messages only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from agent.fhir_facts import FhirClinicalBundle
from hl7v2.errors import UnsupportedMessageTypeError
from hl7v2.parser import HL7Message, ObservationResult

# HL7 v2 coding-system tokens (OBX-3 / OBR-4 component 3) to FHIR system URIs.
_CODING_SYSTEM_URIS = {
    "LN": "http://loinc.org",
    "LOINC": "http://loinc.org",
    "SCT": "http://snomed.info/sct",
    "SNOMED": "http://snomed.info/sct",
    "UCUM": "http://unitsofmeasure.org",
}


@dataclass
class PatientContext:
    """Patient identity + visit context mapped from an ADT^A01 message.

    ``patient_id`` mirrors ``schemas.cases.Case.patient_id``: the identity key
    the copilot uses for structured fact fusion.
    """

    patient_id: str
    family_name: str = ""
    given_name: str = ""
    birth_date: str = ""
    administrative_sex: str = ""
    event_type: str = ""
    patient_class: str = ""
    assigned_location: str = ""
    admit_datetime: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MappedBundle:
    """ORU^R01 mapping result: a FhirClinicalBundle plus its golden view."""

    bundle: FhirClinicalBundle = field(
        default_factory=lambda: FhirClinicalBundle(
            observations_by_loinc={}, conditions=[], medications=[]
        )
    )

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable view of the observation resources (deterministic)."""
        return {
            "observations_by_loinc": self.bundle.observations_by_loinc,
            "conditions": self.bundle.conditions,
            "medications": self.bundle.medications,
        }


def map_adt(message: HL7Message) -> PatientContext:
    """Map a parsed ADT^A01 message to a :class:`PatientContext`."""
    if message.message_type != "ADT^A01":
        raise UnsupportedMessageTypeError(
            f"map_adt expects ADT^A01, got {message.message_type!r}",
            segment_id="MSH",
        )
    pid = message.patient
    visit = message.visit
    return PatientContext(
        patient_id=pid.primary_id if pid else "",
        family_name=pid.family_name if pid else "",
        given_name=pid.given_name if pid else "",
        birth_date=_dtm_to_iso_date(pid.birth_date) if pid else "",
        administrative_sex=pid.administrative_sex if pid else "",
        event_type=message.event_type,
        patient_class=visit.patient_class if visit else "",
        assigned_location=visit.assigned_location if visit else "",
        admit_datetime=_dtm_to_iso(visit.admit_datetime) if visit else "",
    )


def map_oru(message: HL7Message) -> MappedBundle:
    """Map a parsed ORU^R01 message to a :class:`FhirClinicalBundle`."""
    if message.message_type != "ORU^R01":
        raise UnsupportedMessageTypeError(
            f"map_oru expects ORU^R01, got {message.message_type!r}",
            segment_id="MSH",
        )
    observations_by_loinc: dict[str, list[dict[str, Any]]] = {}
    for obx in message.observations:
        key, resource = _obx_to_observation(obx)
        observations_by_loinc.setdefault(key, []).append(resource)
    bundle = FhirClinicalBundle(
        observations_by_loinc=observations_by_loinc,
        conditions=[],
        medications=[],
    )
    return MappedBundle(bundle=bundle)


def _obx_to_observation(obx: ObservationResult) -> tuple[str, dict[str, Any]]:
    """Build a FHIR R4B Observation resource dict from an OBX segment."""
    system = _system_uri(obx.identifier_coding_system)
    key = f"{system}|{obx.identifier_code}"
    coding: dict[str, Any] = {"system": system, "code": obx.identifier_code}
    if obx.identifier_text:
        coding["display"] = obx.identifier_text
    resource: dict[str, Any] = {
        "resourceType": "Observation",
        "status": _result_status(obx.result_status),
        "code": {"coding": [coding]},
    }
    value = obx.typed_value()
    if isinstance(value, float):
        quantity: dict[str, Any] = {"value": value}
        if obx.units:
            quantity["unit"] = obx.units
            quantity["system"] = "http://unitsofmeasure.org"
            quantity["code"] = obx.units
        resource["valueQuantity"] = quantity
    else:
        resource["valueString"] = value
    effective = _dtm_to_iso(obx.observation_datetime)
    if effective:
        resource["effectiveDateTime"] = effective
    return key, resource


def _system_uri(coding_system: str) -> str:
    token = coding_system.strip().upper()
    return _CODING_SYSTEM_URIS.get(token, coding_system or "urn:unknown-system")


def _result_status(hl7_status: str) -> str:
    """Map an OBX-11 result status to a FHIR Observation status."""
    mapping = {"F": "final", "P": "preliminary", "C": "corrected", "X": "cancelled"}
    return mapping.get(hl7_status.strip().upper(), "final")


def _dtm_to_iso(dtm: str) -> str:
    """Convert an HL7 v2 DTM (YYYYMMDD[HHMM[SS]]) to a full ISO-8601 datetime.

    A full datetime (with a time component and UTC offset) is emitted even for
    date-only inputs, because the downstream fact resolver coerces the string
    through ``datetime.fromisoformat`` and expects a datetime, not a date.
    """
    digits = _dtm_digits(dtm)
    if len(digits) < 8:
        return ""
    year, month, day = digits[0:4], digits[4:6], digits[6:8]
    hour = digits[8:10] if len(digits) >= 10 else "00"
    minute = digits[10:12] if len(digits) >= 12 else "00"
    second = digits[12:14] if len(digits) >= 14 else "00"
    return f"{year}-{month}-{day}T{hour}:{minute}:{second}+00:00"


def _dtm_to_iso_date(dtm: str) -> str:
    """Convert an HL7 v2 DTM to an ISO-8601 date (YYYY-MM-DD)."""
    digits = _dtm_digits(dtm)
    if len(digits) < 8:
        return ""
    return f"{digits[0:4]}-{digits[4:6]}-{digits[6:8]}"


def _dtm_digits(dtm: str) -> str:
    """Strip any timezone offset / fractional part and keep leading digits."""
    core = dtm.strip()
    for sep in ("+", "-"):
        idx = core.find(sep)
        if idx > 0:
            core = core[:idx]
    core = core.split(".", 1)[0]
    return "".join(ch for ch in core if ch.isdigit())
