"""HL7 v2.x message parser (ADT^A01 + ORU^R01 subset).

A hand-rolled, dependency-free parser for a documented subset of HL7 v2.x. It
resolves the encoding characters from the MSH header (the canonical HL7 v2
bootstrap: MSH-1 is the field separator, MSH-2 declares component / repetition /
escape / subcomponent), validates the message envelope (version + message
type), and parses the segments the copilot's ingestion boundaries need:

* ``ADT^A01`` (patient admit): MSH, EVN, PID, PV1
* ``ORU^R01`` (observation result): MSH, PID, PV1, OBR, OBX

Only these two message types and the segments above are understood. Any other
segment is tolerated and ignored (not validated), mirroring the "map only what
the agent needs" stance of the X12 278 layer. Supported segments, fields, and
the two mapping boundaries are documented in ``hl7v2/README.md``.

This is a demo-scope v2 subset, not a certified HL7 interface engine: no
MLLP framing, no ACK generation, no Z-segment or conformance-profile handling,
no full data-type validation. Synthetic self-authored messages only.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hl7v2.errors import (
    EmptyMessageError,
    InvalidDelimiterError,
    InvalidSegmentError,
    MissingSegmentError,
    UnsupportedMessageTypeError,
    UnsupportedVersionError,
)

# Message types this subset routes. Anything else raises.
SUPPORTED_MESSAGE_TYPES = frozenset({"ADT^A01", "ORU^R01"})

# Segments this subset understands. Others are tolerated and ignored.
SUPPORTED_SEGMENTS = frozenset({"MSH", "EVN", "PID", "PV1", "OBR", "OBX"})

_MIN_MSH_LEN = 8  # "MSH" + field sep + 4 encoding chars + at least one field sep


@dataclass(frozen=True)
class Delimiters:
    """The five HL7 v2 delimiters resolved from an MSH header."""

    field: str
    component: str
    repetition: str
    escape: str
    subcomponent: str

    def distinct(self) -> bool:
        chars = {
            self.field,
            self.component,
            self.repetition,
            self.escape,
            self.subcomponent,
        }
        return len(chars) == 5


@dataclass(frozen=True)
class Segment:
    """A tokenized non-MSH segment: id plus 1-based field strings.

    ``fields[0]`` is the segment id, so ``field(n)`` returns the HL7 1-based
    field n directly (PID-3 -> ``fields[3]``).
    """

    segment_id: str
    fields: list[str]

    def field(self, index: int, default: str = "") -> str:
        if 0 <= index < len(self.fields):
            return self.fields[index]
        return default


@dataclass(frozen=True)
class MSHHeader:
    """Parsed MSH envelope."""

    field_separator: str
    encoding_characters: str
    sending_application: str
    sending_facility: str
    receiving_application: str
    receiving_facility: str
    message_datetime: str
    message_code: str
    trigger_event: str
    message_structure: str
    message_control_id: str
    processing_id: str
    version: str

    @property
    def message_type(self) -> str:
        return f"{self.message_code}^{self.trigger_event}"


@dataclass(frozen=True)
class PatientIdentifier:
    """One entry of the PID-3 patient identifier list."""

    id_value: str
    assigning_authority: str = ""
    identifier_type_code: str = ""


@dataclass
class PatientIdentification:
    """Parsed PID segment (demographics subset)."""

    set_id: str = ""
    identifiers: list[PatientIdentifier] = field(default_factory=list)
    family_name: str = ""
    given_name: str = ""
    middle_name: str = ""
    birth_date: str = ""
    administrative_sex: str = ""

    @property
    def primary_id(self) -> str:
        return self.identifiers[0].id_value if self.identifiers else ""


@dataclass
class PatientVisit:
    """Parsed PV1 segment (visit subset)."""

    set_id: str = ""
    patient_class: str = ""
    assigned_location: str = ""
    visit_number: str = ""
    admit_datetime: str = ""


@dataclass
class ObservationRequest:
    """Parsed OBR segment (order subset)."""

    set_id: str = ""
    service_code: str = ""
    service_text: str = ""
    service_coding_system: str = ""
    observation_datetime: str = ""


@dataclass
class ObservationResult:
    """Parsed OBX segment (typed result subset)."""

    set_id: str = ""
    value_type: str = ""
    identifier_code: str = ""
    identifier_text: str = ""
    identifier_coding_system: str = ""
    value_raw: str = ""
    units: str = ""
    abnormal_flags: str = ""
    result_status: str = ""
    observation_datetime: str = ""

    def typed_value(self) -> float | str:
        """Return a float for NM (numeric) results, else the raw string."""
        if self.value_type == "NM":
            try:
                return float(self.value_raw)
            except ValueError:
                return self.value_raw
        return self.value_raw


@dataclass
class HL7Message:
    """Intermediate structured view of a parsed ADT^A01 / ORU^R01 message."""

    header: MSHHeader
    event_type: str = ""
    event_datetime: str = ""
    patient: PatientIdentification | None = None
    visit: PatientVisit | None = None
    order: ObservationRequest | None = None
    observations: list[ObservationResult] = field(default_factory=list)

    @property
    def message_type(self) -> str:
        return self.header.message_type


def detect_delimiters(message: str) -> Delimiters:
    """Resolve the five HL7 v2 delimiters from the MSH header."""
    if not message.strip():
        raise EmptyMessageError("message is empty")
    if not message.startswith("MSH"):
        raise MissingSegmentError(
            "message does not start with an MSH header", segment_id="MSH"
        )
    if len(message) < _MIN_MSH_LEN:
        raise InvalidDelimiterError(
            "MSH header too short to resolve encoding characters", segment_id="MSH"
        )
    field_sep = message[3]
    if field_sep.isalnum() or field_sep.isspace():
        raise InvalidDelimiterError(
            "MSH-1 field separator is not a delimiter character", segment_id="MSH"
        )
    encoding = message[4 : message.find(field_sep, 4)]
    if len(encoding) != 4:
        raise InvalidDelimiterError(
            "MSH-2 must declare exactly four encoding characters", segment_id="MSH"
        )
    delimiters = Delimiters(
        field=field_sep,
        component=encoding[0],
        repetition=encoding[1],
        escape=encoding[2],
        subcomponent=encoding[3],
    )
    if not delimiters.distinct():
        raise InvalidDelimiterError(
            "MSH declares non-distinct delimiters", segment_id="MSH"
        )
    return delimiters


def split_segments(message: str) -> list[str]:
    """Split a message into raw segment strings on the segment terminator.

    HL7 v2 terminates segments with a carriage return; real-world carriers vary
    (``\\r``, ``\\n``, ``\\r\\n``). All are accepted, and blank lines dropped.
    """
    normalized = message.replace("\r\n", "\r").replace("\n", "\r")
    return [chunk for chunk in normalized.split("\r") if chunk.strip()]


def tokenize(message: str) -> tuple[list[Segment], MSHHeader, Delimiters]:
    """Split a message into segments and parse the MSH envelope."""
    delimiters = detect_delimiters(message)
    raw_segments = split_segments(message)
    header = _parse_msh(raw_segments[0], delimiters)

    segments: list[Segment] = []
    for raw in raw_segments[1:]:
        fields = raw.split(delimiters.field)
        segments.append(Segment(segment_id=fields[0], fields=fields))
    return segments, header, delimiters


def parse_message(message: str) -> HL7Message:
    """Parse an HL7 v2 ADT^A01 / ORU^R01 message into an :class:`HL7Message`."""
    segments, header, delimiters = tokenize(message)

    if header.message_type not in SUPPORTED_MESSAGE_TYPES:
        raise UnsupportedMessageTypeError(
            f"message type {header.message_type!r} is outside this subset "
            f"(supported: {', '.join(sorted(SUPPORTED_MESSAGE_TYPES))})",
            segment_id="MSH",
        )

    parsed = HL7Message(header=header)
    for seg in segments:
        sid = seg.segment_id
        if sid == "EVN":
            parsed.event_type = _leaf(seg.field(1), delimiters)
            parsed.event_datetime = _first_component(seg.field(2), delimiters)
        elif sid == "PID":
            parsed.patient = _parse_pid(seg, delimiters)
        elif sid == "PV1":
            parsed.visit = _parse_pv1(seg, delimiters)
        elif sid == "OBR":
            parsed.order = _parse_obr(seg, delimiters)
        elif sid == "OBX":
            parsed.observations.append(_parse_obx(seg, delimiters))

    _validate_required(parsed)
    return parsed


def _validate_required(parsed: HL7Message) -> None:
    """Enforce the minimum segments each supported message type needs."""
    if parsed.patient is None:
        raise MissingSegmentError(
            f"{parsed.message_type} requires a PID segment", segment_id="PID"
        )
    if parsed.message_type == "ORU^R01" and not parsed.observations:
        raise MissingSegmentError(
            "ORU^R01 requires at least one OBX result", segment_id="OBX"
        )


def _parse_msh(raw: str, delimiters: Delimiters) -> MSHHeader:
    """Parse the MSH segment.

    MSH is special: MSH-1 is the field separator itself, so after splitting on
    the field separator ``parts[1]`` is MSH-2 and MSH-n (n>=2) is ``parts[n-1]``.
    """
    parts = raw.split(delimiters.field)
    if len(parts) < 12:
        raise InvalidSegmentError(
            "MSH header is truncated (needs through MSH-12 version)",
            segment_id="MSH",
        )

    def msh(n: int) -> str:
        return parts[n - 1] if 0 <= n - 1 < len(parts) else ""

    version = _first_component(msh(12), delimiters)
    if not version.startswith("2."):
        raise UnsupportedVersionError(
            f"MSH-12 {version!r} is not an HL7 v2.x version", segment_id="MSH"
        )

    message_type_field = msh(9)
    comps = _components(message_type_field, delimiters)
    return MSHHeader(
        field_separator=delimiters.field,
        encoding_characters=parts[1],
        sending_application=_leaf(msh(3), delimiters),
        sending_facility=_leaf(msh(4), delimiters),
        receiving_application=_leaf(msh(5), delimiters),
        receiving_facility=_leaf(msh(6), delimiters),
        message_datetime=_first_component(msh(7), delimiters),
        message_code=_at(comps, 0),
        trigger_event=_at(comps, 1),
        message_structure=_at(comps, 2),
        message_control_id=_leaf(msh(10), delimiters),
        processing_id=_first_component(msh(11), delimiters),
        version=version,
    )


def _parse_pid(seg: Segment, delimiters: Delimiters) -> PatientIdentification:
    identifiers: list[PatientIdentifier] = []
    for rep in _repetitions(seg.field(3), delimiters):
        comps = _components(rep, delimiters)
        if not _at(comps, 0):
            continue
        identifiers.append(
            PatientIdentifier(
                id_value=_unescape(_at(comps, 0), delimiters),
                assigning_authority=_unescape(_at(comps, 3), delimiters),
                identifier_type_code=_unescape(_at(comps, 4), delimiters),
            )
        )
    name_comps = _components(seg.field(5), delimiters)
    return PatientIdentification(
        set_id=_leaf(seg.field(1), delimiters),
        identifiers=identifiers,
        family_name=_unescape(_at(name_comps, 0), delimiters),
        given_name=_unescape(_at(name_comps, 1), delimiters),
        middle_name=_unescape(_at(name_comps, 2), delimiters),
        birth_date=_first_component(seg.field(7), delimiters),
        administrative_sex=_leaf(seg.field(8), delimiters),
    )


def _parse_pv1(seg: Segment, delimiters: Delimiters) -> PatientVisit:
    return PatientVisit(
        set_id=_leaf(seg.field(1), delimiters),
        patient_class=_leaf(seg.field(2), delimiters),
        assigned_location=_first_component(seg.field(3), delimiters),
        visit_number=_first_component(seg.field(19), delimiters),
        admit_datetime=_first_component(seg.field(44), delimiters),
    )


def _parse_obr(seg: Segment, delimiters: Delimiters) -> ObservationRequest:
    service = _components(seg.field(4), delimiters)
    return ObservationRequest(
        set_id=_leaf(seg.field(1), delimiters),
        service_code=_unescape(_at(service, 0), delimiters),
        service_text=_unescape(_at(service, 1), delimiters),
        service_coding_system=_unescape(_at(service, 2), delimiters),
        observation_datetime=_first_component(seg.field(7), delimiters),
    )


def _parse_obx(seg: Segment, delimiters: Delimiters) -> ObservationResult:
    identifier = _components(seg.field(3), delimiters)
    units = _components(seg.field(6), delimiters)
    return ObservationResult(
        set_id=_leaf(seg.field(1), delimiters),
        value_type=_leaf(seg.field(2), delimiters),
        identifier_code=_unescape(_at(identifier, 0), delimiters),
        identifier_text=_unescape(_at(identifier, 1), delimiters),
        identifier_coding_system=_unescape(_at(identifier, 2), delimiters),
        value_raw=_unescape(_first_component(seg.field(5), delimiters), delimiters),
        units=_unescape(_at(units, 0), delimiters),
        abnormal_flags=_leaf(seg.field(8), delimiters),
        result_status=_leaf(seg.field(11), delimiters),
        observation_datetime=_first_component(seg.field(14), delimiters),
    )


def _components(value: str, delimiters: Delimiters) -> list[str]:
    return value.split(delimiters.component)


def _repetitions(value: str, delimiters: Delimiters) -> list[str]:
    return [rep for rep in value.split(delimiters.repetition) if rep]


def _first_component(value: str, delimiters: Delimiters) -> str:
    return _unescape(_components(value, delimiters)[0], delimiters)


def _leaf(value: str, delimiters: Delimiters) -> str:
    """Unescape a whole-field leaf value (no component structure expected)."""
    return _unescape(value, delimiters)


def _at(items: list[str], index: int) -> str:
    return items[index] if 0 <= index < len(items) else ""


def _unescape(value: str, delimiters: Delimiters) -> str:
    """Resolve HL7 v2 escape sequences to their literal delimiter characters."""
    if delimiters.escape not in value:
        return value
    e = delimiters.escape
    replacements = {
        f"{e}F{e}": delimiters.field,
        f"{e}S{e}": delimiters.component,
        f"{e}T{e}": delimiters.subcomponent,
        f"{e}R{e}": delimiters.repetition,
        f"{e}E{e}": delimiters.escape,
    }
    result = value
    for token, literal in replacements.items():
        result = result.replace(token, literal)
    return result
