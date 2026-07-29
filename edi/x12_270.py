"""X12 270 eligibility-inquiry parser (self-authored demo subset).

A hand-rolled parser for a *self-authored* subset of the X12 270 health-care
eligibility/benefit inquiry. It reads a synthetic 270-shaped interchange into a
typed :class:`EligibilityInquiry` so the deterministic responder in
``edi.eligibility_271`` can emit a 271-shaped response from the repo's own
synthetic coverage table.

Scope and honesty (see edi/README.md for the full note):

* **Self-authored subset**, not the real 005010X279 implementation guide. Only
  the envelope/inquiry shapes this demo needs are modeled; everything else is
  tolerated and ignored, not validated.
* **Invented service-type vocabulary.** Real 270 inquiries carry externally
  maintained service type codes in ``EQ01``. This demo deliberately does NOT
  reproduce that content: it carries an invented ``SRV-*`` vocabulary defined in
  ``edi.eligibility_271``. No real service type code list appears anywhere.
* **Invented reject vocabulary.** Real 270/271 pairs report rejects in ``AAA``
  segments using externally maintained reject reason codes. This demo carries
  rejects in an invented ``ZRJC`` segment using a small self-authored ``RJ-*``
  vocabulary. That carrier ID is four characters, and an X12 segment ID is two
  or three, so it cannot collide with a real segment (see
  :mod:`edi.invented_segments`).
* **Synthetic data only.** Fixtures are self-authored; no PHI, no real payer
  traffic, not affiliated with any company or product.
* This simulates the payer side for demo purposes. It is not HIPAA-certified EDI
  tooling, it is not a clearinghouse integration, and it returns no real
  coverage determinations.

The tokenizer, delimiter bootstrap, and structured error hierarchy are shared
with the existing 278 and 835 layers (``edi.tokenizer`` / ``edi.errors``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from edi.errors import InvalidSegmentError, MissingSegmentError
from edi.tokenizer import Segment, tokenize

# Segments this self-authored subset understands. Others are ignored, not errors.
SUPPORTED_SEGMENTS = frozenset(
    {
        "ISA",
        "GS",
        "ST",
        "BHT",
        "HL",
        "NM1",
        "DMG",
        "DTP",
        "EQ",
        "REF",
        "SE",
        "GE",
        "IEA",
    }
)

# Required for a usable inquiry in this subset: the transaction header, the
# beginning-of-transaction reference, and at least one benefit inquiry line.
_REQUIRED_SEGMENTS = ("ST", "BHT", "EQ")

# DTP date-time qualifier used for the service date in this subset.
_SERVICE_DATE_QUALIFIER = "472"


@dataclass
class RequestingProvider:
    """Information receiver / requesting provider (NM1*1P)."""

    last_name: str = ""
    first_name: str = ""
    npi: str | None = None


@dataclass
class Subscriber:
    """Subscriber whose coverage is being checked (NM1*IL plus DMG)."""

    last_name: str = ""
    first_name: str = ""
    member_id: str | None = None
    birth_date: str | None = None  # DMG02, CCYYMMDD
    gender: str | None = None  # DMG03, carried verbatim, never interpreted


@dataclass
class EligibilityInquiry:
    """Intermediate structured view of a parsed 270 inquiry (subset)."""

    transaction_control: str = ""
    submitter_reference: str = ""  # BHT03
    payer_name: str = ""
    provider: RequestingProvider = field(default_factory=RequestingProvider)
    subscriber: Subscriber = field(default_factory=Subscriber)
    # EQ01 values: self-authored SRV-* tokens, never a real service type code.
    service_types: list[str] = field(default_factory=list)
    service_date: str | None = None  # DTP*472

    def require_member_key(self) -> str:
        """Return the member id, or raise if the inquiry cannot be resolved.

        Coverage lookup is keyed on the subscriber member id carried in
        ``NM1*IL`` with an ``MI`` qualifier. An inquiry without one cannot be
        answered, so this fails loudly rather than resolving against a guess.
        """
        if not self.subscriber.member_id:
            raise InvalidSegmentError(
                "cannot resolve eligibility; NM1*IL carries no MI member id",
                segment_id="NM1",
            )
        return self.subscriber.member_id


def parse_270_inquiry(interchange: str) -> EligibilityInquiry:
    """Parse a 270 eligibility inquiry (subset) into an EligibilityInquiry."""
    segments, _delimiters = tokenize(interchange)
    _require_segments(segments)

    inquiry = EligibilityInquiry()

    for seg in segments:
        sid = seg.segment_id
        if sid == "ST":
            inquiry.transaction_control = seg.element(2)
        elif sid == "BHT":
            inquiry.submitter_reference = seg.element(3)
        elif sid == "NM1":
            _apply_nm1(seg, inquiry)
        elif sid == "DMG":
            _apply_dmg(seg, inquiry)
        elif sid == "DTP":
            if seg.element(1) == _SERVICE_DATE_QUALIFIER:
                inquiry.service_date = seg.element(3) or None
        elif sid == "EQ":
            inquiry.service_types.append(_parse_eq(seg))

    return inquiry


def _require_segments(segments: list[Segment]) -> None:
    present = {seg.segment_id for seg in segments}
    for required in _REQUIRED_SEGMENTS:
        if required not in present:
            raise MissingSegmentError(
                f"required segment {required} not found in interchange",
                segment_id=required,
            )


def _apply_nm1(seg: Segment, inquiry: EligibilityInquiry) -> None:
    entity = seg.element(1)
    id_qualifier = seg.element(8)
    id_value = seg.element(9)
    if entity == "PR":
        inquiry.payer_name = seg.element(3)
    elif entity == "1P":
        inquiry.provider = RequestingProvider(
            last_name=seg.element(3),
            first_name=seg.element(4),
            npi=id_value if id_qualifier == "XX" and id_value else None,
        )
    elif entity == "IL":
        inquiry.subscriber = Subscriber(
            last_name=seg.element(3),
            first_name=seg.element(4),
            member_id=id_value if id_qualifier == "MI" and id_value else None,
        )


def _apply_dmg(seg: Segment, inquiry: EligibilityInquiry) -> None:
    """Attach demographics to the subscriber parsed from an earlier NM1*IL."""
    if seg.element(1) != "D8":
        # Only the CCYYMMDD date format is modeled in this subset.
        return
    inquiry.subscriber.birth_date = seg.element(2) or None
    inquiry.subscriber.gender = seg.element(3) or None


def _parse_eq(seg: Segment) -> str:
    """Read one benefit-inquiry line's self-authored SRV-* service type."""
    service_type = seg.element(1)
    if not service_type:
        raise InvalidSegmentError(
            "EQ is missing a service type (EQ01)", segment_id="EQ"
        )
    return service_type
