"""X12 835 remittance parser (self-authored demo subset).

A hand-rolled parser for a *self-authored* subset of the X12 835 health-care
claim payment / remittance advice. It reads a synthetic 835-shaped interchange
into a typed :class:`RemittanceAdvice` (claims, paid vs billed amounts, and
denial reasons) so the deterministic triage layer in ``edi.denial_triage`` can
recommend a next action per claim.

Scope and honesty (see edi/README.md for the full note):

* **Self-authored subset**, not the real 005010X221 implementation guide. Only
  the envelope/claim shapes the triage demo needs are modeled; everything else is
  tolerated and ignored, not validated.
* **Invented denial-code system.** Real 835 remittances carry adjustment reasons
  in ``CAS`` segments using externally maintained CARC/RARC code lists. This demo
  deliberately does NOT reproduce those. It carries denial reasons in an invented
  ``DRC`` segment using a small self-authored ``DR-*`` code vocabulary defined in
  ``edi.denial_triage``. No real CARC/RARC/CAS content appears anywhere.
* **Synthetic data only.** Fixtures are self-authored; no PHI, no real payer
  traffic, not affiliated with any company or product.
* This simulates the provider-side remittance-review step for demo purposes. It
  is not HIPAA-certified EDI tooling and issues no real determinations.

The tokenizer, delimiter bootstrap, and structured error hierarchy are shared
with the existing 278 layer (``edi.tokenizer`` / ``edi.errors``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from edi.errors import (
    InvalidSegmentError,
    MissingSegmentError,
)
from edi.tokenizer import Segment, tokenize

# Segments this self-authored subset understands. Others are ignored, not errors.
SUPPORTED_SEGMENTS = frozenset(
    {
        "ISA",
        "GS",
        "ST",
        "BPR",
        "TRN",
        "CLP",
        "SVC",
        "DRC",  # invented denial-reason carrier (NOT a real X12 segment)
        "PLB",
        "SE",
        "GE",
        "IEA",
    }
)

# Required for a usable remittance in this subset: the transaction header and at
# least one claim-payment line.
_REQUIRED_SEGMENTS = ("ST", "CLP")


def _money(value: str, *, segment_id: str, field_name: str) -> Decimal:
    """Parse a monetary element to Decimal, or raise a structured error.

    ``Decimal()`` silently accepts ``NaN``, ``Infinity``, and signalling forms,
    which are never valid remittance amounts. Finite exponent forms (e.g.
    ``1E2``) are accepted; non-finite values are rejected as malformed.
    """
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise InvalidSegmentError(
            f"{field_name} is not a valid amount: {value!r}",
            segment_id=segment_id,
        ) from exc
    if not amount.is_finite():
        raise InvalidSegmentError(
            f"{field_name} is not a finite amount: {value!r}",
            segment_id=segment_id,
        )
    return amount


@dataclass
class ServiceLine:
    """A single service-line payment (SVC) with any line-level denial codes."""

    procedure: str = ""  # self-authored PROC-* identifier (not a real CPT/HCPCS)
    billed: Decimal = Decimal("0")
    paid: Decimal = Decimal("0")
    denial_codes: list[str] = field(default_factory=list)


@dataclass
class ClaimPayment:
    """A claim-level payment (CLP) with its service lines and denial reasons."""

    claim_ref: str = ""
    status: str = ""  # self-authored token: PAID / PART / DENY
    billed: Decimal = Decimal("0")
    paid: Decimal = Decimal("0")
    patient_responsibility: Decimal = Decimal("0")
    denial_codes: list[str] = field(default_factory=list)  # claim-level DRC
    service_lines: list[ServiceLine] = field(default_factory=list)

    def all_denial_codes(self) -> list[str]:
        """Claim-level plus every line-level denial code, in document order."""
        codes = list(self.denial_codes)
        for line in self.service_lines:
            codes.extend(line.denial_codes)
        return codes


@dataclass
class RemittanceAdvice:
    """Intermediate structured view of a parsed 835 remittance (subset)."""

    transaction_control: str = ""
    trace_number: str = ""
    total_paid: Decimal | None = None  # BPR02 if present
    claims: list[ClaimPayment] = field(default_factory=list)


def parse_835(interchange: str) -> RemittanceAdvice:
    """Parse an 835 remittance interchange (subset) into a RemittanceAdvice."""
    segments, _delimiters = tokenize(interchange)
    _require_segments(segments)

    remittance = RemittanceAdvice()
    current_claim: ClaimPayment | None = None
    current_line: ServiceLine | None = None

    for seg in segments:
        sid = seg.segment_id
        if sid == "ST":
            remittance.transaction_control = seg.element(2)
        elif sid == "BPR":
            value = seg.element(2)
            if value:
                remittance.total_paid = _money(
                    value, segment_id="BPR", field_name="BPR02 total paid"
                )
        elif sid == "TRN":
            remittance.trace_number = seg.element(2)
        elif sid == "CLP":
            current_claim = _parse_clp(seg)
            current_line = None
            remittance.claims.append(current_claim)
        elif sid == "SVC":
            if current_claim is None:
                raise InvalidSegmentError(
                    "SVC service line appears before any CLP claim",
                    segment_id="SVC",
                )
            current_line = _parse_svc(seg)
            current_claim.service_lines.append(current_line)
        elif sid == "DRC":
            _apply_drc(seg, current_claim, current_line)

    return remittance


def _require_segments(segments: list[Segment]) -> None:
    present = {seg.segment_id for seg in segments}
    for required in _REQUIRED_SEGMENTS:
        if required not in present:
            raise MissingSegmentError(
                f"required segment {required} not found in interchange",
                segment_id=required,
            )


def _parse_clp(seg: Segment) -> ClaimPayment:
    claim_ref = seg.element(1)
    if not claim_ref:
        raise InvalidSegmentError(
            "CLP is missing a claim reference (CLP01)", segment_id="CLP"
        )
    return ClaimPayment(
        claim_ref=claim_ref,
        status=seg.element(2),
        billed=_money(seg.element(3, "0"), segment_id="CLP", field_name="CLP03 billed"),
        paid=_money(seg.element(4, "0"), segment_id="CLP", field_name="CLP04 paid"),
        patient_responsibility=_money(
            seg.element(5, "0"), segment_id="CLP", field_name="CLP05 patient resp"
        ),
    )


def _parse_svc(seg: Segment) -> ServiceLine:
    return ServiceLine(
        procedure=seg.element(1),
        billed=_money(seg.element(2, "0"), segment_id="SVC", field_name="SVC02 billed"),
        paid=_money(seg.element(3, "0"), segment_id="SVC", field_name="SVC03 paid"),
    )


def _apply_drc(
    seg: Segment,
    current_claim: ClaimPayment | None,
    current_line: ServiceLine | None,
) -> None:
    """Attach a DRC denial code to the current line, else the current claim."""
    code = seg.element(1)
    if not code:
        raise InvalidSegmentError(
            "DRC is missing a denial code (DRC01)", segment_id="DRC"
        )
    if current_claim is None:
        raise InvalidSegmentError(
            "DRC denial reason appears before any CLP claim", segment_id="DRC"
        )
    if current_line is not None:
        current_line.denial_codes.append(code)
    else:
        current_claim.denial_codes.append(code)
