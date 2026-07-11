"""X12 278 REQUEST parser (005010X217 subset).

Parses a health-care-services-review REQUEST into an intermediate
:class:`Request278`, then maps that subset onto the agent's existing
``schemas.cases.Case`` input. Only the segments the agent needs are mapped;
everything else is tolerated and ignored. Supported segments and qualifiers
are documented in edi/README.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from edi.errors import (
    InvalidSegmentError,
    MissingSegmentError,
)
from edi.tokenizer import Delimiters, Segment, split_components, tokenize
from schemas.cases import Case

# Segments this subset understands. Others are ignored, not errors.
SUPPORTED_SEGMENTS = frozenset(
    {
        "ISA",
        "GS",
        "ST",
        "BHT",
        "HL",
        "NM1",
        "UM",
        "DTP",
        "HI",
        "REF",
        "MSG",
        "SE",
        "GE",
        "IEA",
    }
)

# Required for a usable review request in this subset.
_REQUIRED_SEGMENTS = ("ST", "BHT", "UM")

# Diagnosis code-list qualifiers we recognize in HI (ICD-10-CM).
_ICD10_QUALIFIERS = frozenset({"ABK", "ABF", "BK", "BF"})


@dataclass
class Provider:
    """Requesting provider (NM1*1P)."""

    last_name: str = ""
    first_name: str = ""
    npi: str | None = None


@dataclass
class Patient:
    """Subscriber / patient (NM1*IL)."""

    last_name: str = ""
    first_name: str = ""
    member_id: str | None = None


@dataclass
class Request278:
    """Intermediate structured view of a parsed 278 request."""

    transaction_control: str = ""
    submitter_reference: str = ""  # BHT03 -> case_id
    payer_name: str = ""
    provider: Provider = field(default_factory=Provider)
    patient: Patient = field(default_factory=Patient)
    request_category: str = ""  # UM01
    certification_type: str = ""  # UM02
    service_type: str = ""  # UM03
    service_date: str | None = None  # DTP*472
    diagnosis_codes: list[str] = field(default_factory=list)  # HI ICD-10
    drug: str = ""  # REF*ZZ ... DRUG
    condition: str = ""  # REF*ZZ ... CONDITION
    clinical_note: str = ""  # concatenated MSG segments

    def to_case(self) -> Case:
        """Map the subset onto the agent's Case input structure."""
        missing: list[str] = []
        if not self.submitter_reference:
            missing.append("BHT03 (case reference)")
        if not self.drug:
            missing.append("REF*ZZ DRUG (requested drug)")
        if not self.condition:
            missing.append("REF*ZZ CONDITION (indication)")
        if len(self.clinical_note) < 50:
            missing.append("MSG (clinical narrative >= 50 chars)")
        if missing:
            raise InvalidSegmentError(
                "cannot map 278 request to a Case; missing/short: " + ", ".join(missing)
            )
        return Case(
            case_id=self.submitter_reference,
            clinical_note=self.clinical_note,
            payer_policy=_placeholder_policy(self.drug, self.condition),
            drug=self.drug,
            condition=self.condition,
            patient_id=self.patient.member_id,
        )


def _placeholder_policy(drug: str, condition: str):  # type: ignore[no-untyped-def]
    """A minimal policy stub.

    The agent looks up the authoritative payer policy from the clinical-data
    service using ``drug`` + ``condition``; the 278 only needs to carry those
    keys. This stub satisfies the Case model without asserting policy content.
    """
    from schemas.policies import PayerPolicy

    return PayerPolicy(
        drug=drug,
        condition=condition,
        required_criteria_fields=["diagnosis_confirmed"],
        rules="Policy resolved downstream from drug and condition keys.",
    )


def parse_278_request(interchange: str) -> Request278:
    """Parse a 278 request interchange into a :class:`Request278`."""
    segments, delimiters = tokenize(interchange)
    _require_segments(segments)

    request = Request278()
    note_chunks: list[str] = []
    current_hl_level = ""

    for seg in segments:
        sid = seg.segment_id
        if sid == "ST":
            request.transaction_control = seg.element(2)
        elif sid == "BHT":
            request.submitter_reference = seg.element(3)
        elif sid == "HL":
            current_hl_level = seg.element(3)
        elif sid == "NM1":
            _apply_nm1(seg, request)
        elif sid == "UM":
            request.request_category = seg.element(1)
            request.certification_type = seg.element(2)
            request.service_type = seg.element(3)
        elif sid == "DTP":
            if seg.element(1) == "472":
                request.service_date = seg.element(3) or None
        elif sid == "HI":
            _apply_hi(seg, request, delimiters)
        elif sid == "REF":
            _apply_ref(seg, request)
        elif sid == "MSG":
            note_chunks.append(seg.element(1))
        _ = current_hl_level  # reserved for future loop-scoped parsing

    request.clinical_note = "".join(note_chunks)
    return request


def _require_segments(segments: list[Segment]) -> None:
    present = {seg.segment_id for seg in segments}
    for required in _REQUIRED_SEGMENTS:
        if required not in present:
            raise MissingSegmentError(
                f"required segment {required} not found in interchange",
                segment_id=required,
            )


def _apply_nm1(seg: Segment, request: Request278) -> None:
    entity = seg.element(1)
    id_qualifier = seg.element(8)
    id_value = seg.element(9)
    if entity == "PR":
        request.payer_name = seg.element(3)
    elif entity == "1P":
        request.provider = Provider(
            last_name=seg.element(3),
            first_name=seg.element(4),
            npi=id_value if id_qualifier == "XX" and id_value else None,
        )
    elif entity == "IL":
        request.patient = Patient(
            last_name=seg.element(3),
            first_name=seg.element(4),
            member_id=id_value if id_qualifier == "MI" and id_value else None,
        )


def _apply_hi(seg: Segment, request: Request278, delimiters: Delimiters) -> None:
    for raw in seg.elements:
        if not raw:
            continue
        components = split_components(raw, delimiters)
        qualifier = components[0]
        if qualifier in _ICD10_QUALIFIERS and len(components) > 1:
            request.diagnosis_codes.append(components[1])


def _apply_ref(seg: Segment, request: Request278) -> None:
    if seg.element(1) != "ZZ":
        return
    value = seg.element(2)
    tag = seg.element(3)
    if tag == "DRUG":
        request.drug = value
    elif tag == "CONDITION":
        request.condition = value
