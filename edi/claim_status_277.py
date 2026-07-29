"""Deterministic 277 claim-status responder over a synthetic claim store.

Given a parsed :class:`~edi.x12_276.ClaimStatusInquiry`, this module resolves a
status per requested claim reference from a small, transparent, self-authored
claim store, and emits a 277-shaped response interchange. There is no scoring
model and no LLM: every status is a pure function of the store, so the output is
fully reproducible offline.

Invented code system (honest scope): the ``CS-*`` statuses below are a demo
vocabulary authored for this project. They are NOT the real claim status
category codes or claim status codes that a production 277 carries in ``STC``
segments, and this store models no real payer's adjudication. Statuses travel in
an invented ``ZCSI`` segment and rejects in an invented ``ZRJC`` segment. Both
carrier IDs are four characters, and an X12 segment ID is two or three, so
neither can collide with a real segment. See :mod:`edi.invented_segments`.

Note on ``CSI``: an earlier revision of this layer used ``CSI`` as the status
carrier and claimed it was not a real X12 segment. That was wrong. ``CSI`` is a
real X12 segment ("Claim Status Information", transaction set 260). The carrier
was renamed to a four-character ID so the claim rests on a length rule rather
than on anyone's recollection of the standard.

Cross-layer note: the finalized claims in the store deliberately mirror the
claim shapes of the 835 layer's self-authored fixtures (same references, same
billed and paid amounts, same self-authored ``DR-*`` denial reasons carried in
the same invented ``DRC`` segment). One synthetic claim can therefore be
followed across both demo layers: asked about with a 276 and reported back with
a 277, or paid or denied on an 835 remittance and triaged. A test asserts the
two stay consistent, so the mirror cannot silently drift.

Role framing: a 277 response is issued by the payer side. This module
**simulates the payer side** for demo purposes. It is demo output only, not a
real claim-status determination.

Status classes:

* ``CS-FINALIZED-PAID`` - adjudication complete, paid in full.
* ``CS-FINALIZED-PARTIAL`` - adjudication complete, paid short of billed.
* ``CS-FINALIZED-DENIED`` - adjudication complete, nothing payable; the
  self-authored denial reasons are echoed.
* ``CS-PENDING-REVIEW`` - received, still in adjudication.
* ``CS-PENDING-DOCUMENTATION`` - received, waiting on requested material.
* ``CS-NOT-FOUND`` - no claim with that reference is on file; the row also
  carries a self-authored reject reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from edi.denial_triage import DENIAL_CODE_TABLE
from edi.encoder import DEFAULT_DELIMITERS, build_isa
from edi.invented_segments import REJECT_SEGMENT, STATUS_SEGMENT
from edi.tokenizer import Delimiters
from edi.x12_276 import ClaimStatusInquiry, parse_276_inquiry

# STATUS_SEGMENT ("ZCSI") and REJECT_SEGMENT ("ZRJC") are defined once in
# edi.invented_segments, which documents why a four-character carrier ID cannot
# collide with a real X12 segment.
#
# DENIAL_SEGMENT is the 835 layer's existing invented denial carrier, reused
# here so one denial vocabulary serves both demo layers. It keeps its
# three-character ID because it already ships on main. Three characters is a
# well-formed segment ID, so its safety rests on a directory check (checked
# against a published X12 segment directory on 2026-07-28 and found absent)
# rather than on the length rule.
DENIAL_SEGMENT = "DRC"


class ClaimStatus(StrEnum):
    """Self-authored claim status for one requested claim reference."""

    FINALIZED_PAID = "CS-FINALIZED-PAID"
    FINALIZED_PARTIAL = "CS-FINALIZED-PARTIAL"
    FINALIZED_DENIED = "CS-FINALIZED-DENIED"
    PENDING_REVIEW = "CS-PENDING-REVIEW"
    PENDING_DOCUMENTATION = "CS-PENDING-DOCUMENTATION"
    NOT_FOUND = "CS-NOT-FOUND"


class ClaimRejectReason(StrEnum):
    """Self-authored, row-level reject reasons (invented, not real AAA)."""

    CLAIM_NOT_FOUND = "RJ-CLAIM-NOT-FOUND"


# Self-authored adjudication tokens, the same PAID/PART/DENY vocabulary the 835
# layer's CLP status element uses, plus PEND for claims still in flight.
_FINALIZED_TOKENS: dict[str, ClaimStatus] = {
    "PAID": ClaimStatus.FINALIZED_PAID,
    "PART": ClaimStatus.FINALIZED_PARTIAL,
    "DENY": ClaimStatus.FINALIZED_DENIED,
}

_PENDING_REASONS: dict[str, ClaimStatus] = {
    "review": ClaimStatus.PENDING_REVIEW,
    "documentation": ClaimStatus.PENDING_DOCUMENTATION,
}


@dataclass(frozen=True)
class StoredClaim:
    """A synthetic claim record in the demo claim store."""

    claim_ref: str
    adjudication: str  # PAID / PART / DENY / PEND (self-authored tokens)
    billed: Decimal
    paid: Decimal = Decimal("0")
    denial_codes: tuple[str, ...] = ()  # self-authored DR-* codes
    pending_reason: str = ""  # "review" or "documentation" when adjudication=PEND


# Single source of truth for the synthetic claim store, rendered as a table in
# edi/README.md. Every reference and amount here is invented. The finalized rows
# mirror the 835 layer's fixture claims (see the cross-layer note above).
CLAIM_STORE: dict[str, StoredClaim] = {
    "CLM-1001": StoredClaim(
        claim_ref="CLM-1001",
        adjudication="PAID",
        billed=Decimal("500.00"),
        paid=Decimal("500.00"),
    ),
    "CLM-2001": StoredClaim(
        claim_ref="CLM-2001",
        adjudication="PAID",
        billed=Decimal("300.00"),
        paid=Decimal("300.00"),
    ),
    "CLM-2002": StoredClaim(
        claim_ref="CLM-2002",
        adjudication="DENY",
        billed=Decimal("420.00"),
        denial_codes=("DR-DOC-MISSING",),
    ),
    "CLM-2003": StoredClaim(
        claim_ref="CLM-2003",
        adjudication="DENY",
        billed=Decimal("260.00"),
        denial_codes=("DR-CODE-INVALID",),
    ),
    "CLM-3001": StoredClaim(
        claim_ref="CLM-3001",
        adjudication="PART",
        billed=Decimal("450.00"),
        paid=Decimal("180.00"),
        denial_codes=("DR-DOC-MISSING",),
    ),
    "CLM-4001": StoredClaim(
        claim_ref="CLM-4001",
        adjudication="DENY",
        billed=Decimal("615.00"),
        denial_codes=("DR-AUTH-ABSENT",),
    ),
    "CLM-5001": StoredClaim(
        claim_ref="CLM-5001",
        adjudication="DENY",
        billed=Decimal("780.00"),
        denial_codes=("DR-DOC-MISSING", "DR-DUPLICATE"),
    ),
    "CLM-6001": StoredClaim(
        claim_ref="CLM-6001",
        adjudication="DENY",
        billed=Decimal("340.00"),
        denial_codes=("DR-COORD-BENEFITS",),
    ),
    "CLM-6002": StoredClaim(
        claim_ref="CLM-6002",
        adjudication="DENY",
        billed=Decimal("295.00"),
        denial_codes=("DR-ELIG-LAPSED",),
    ),
    # Claims still in flight; these have no 835 counterpart by design, because a
    # remittance only exists once adjudication has finished.
    "CLM-7001": StoredClaim(
        claim_ref="CLM-7001",
        adjudication="PEND",
        billed=Decimal("210.00"),
        pending_reason="review",
    ),
    "CLM-7002": StoredClaim(
        claim_ref="CLM-7002",
        adjudication="PEND",
        billed=Decimal("640.00"),
        pending_reason="documentation",
    ),
}


@dataclass(frozen=True)
class ClaimStatusRow:
    """The resolved status for one requested claim reference."""

    claim_ref: str
    status: ClaimStatus
    billed: Decimal | None = None
    paid: Decimal | None = None
    denial_codes: list[str] = field(default_factory=list)
    reject: ClaimRejectReason | None = None
    rationale: str = ""


@dataclass(frozen=True)
class ClaimStatusResponse:
    """Everything the 277 generator needs, resolved and typed."""

    submitter_reference: str
    trace_number: str = ""
    rows: list[ClaimStatusRow] = field(default_factory=list)


def resolve_claim_status(inquiry: ClaimStatusInquiry) -> ClaimStatusResponse:
    """Resolve every requested claim reference against the claim store."""
    return ClaimStatusResponse(
        submitter_reference=inquiry.submitter_reference,
        trace_number=inquiry.trace_number,
        rows=[_resolve_claim_ref(ref) for ref in inquiry.claim_refs],
    )


def _resolve_claim_ref(claim_ref: str) -> ClaimStatusRow:
    """Look one claim reference up and describe its status deterministically."""
    claim = CLAIM_STORE.get(claim_ref)
    if claim is None:
        return ClaimStatusRow(
            claim_ref=claim_ref,
            status=ClaimStatus.NOT_FOUND,
            reject=ClaimRejectReason.CLAIM_NOT_FOUND,
            rationale="No claim with that reference is on file.",
        )

    if claim.adjudication == "PEND":
        status = _PENDING_REASONS.get(claim.pending_reason, ClaimStatus.PENDING_REVIEW)
    else:
        # An unrecognized adjudication token must never be reported as finalized.
        status = _FINALIZED_TOKENS.get(claim.adjudication, ClaimStatus.PENDING_REVIEW)

    return ClaimStatusRow(
        claim_ref=claim_ref,
        status=status,
        billed=claim.billed,
        paid=claim.paid,
        denial_codes=list(claim.denial_codes),
        rationale=_rationale(status, claim),
    )


def _rationale(status: ClaimStatus, claim: StoredClaim) -> str:
    """Deterministic, transparent explanation for one resolved status."""
    if status is ClaimStatus.FINALIZED_PAID:
        return "Adjudication complete; paid in full."
    if status is ClaimStatus.FINALIZED_PARTIAL:
        return "Adjudication complete; paid short of the billed amount."
    if status is ClaimStatus.FINALIZED_DENIED:
        reasons = ", ".join(
            DENIAL_CODE_TABLE[code].description
            for code in claim.denial_codes
            if code in DENIAL_CODE_TABLE
        )
        base = "Adjudication complete; nothing payable."
        return f"{base} {reasons}".strip()
    if status is ClaimStatus.PENDING_DOCUMENTATION:
        return "Received; waiting on requested documentation."
    return "Received; still in adjudication."


def build_277_response(
    inquiry: ClaimStatusInquiry,
    response: ClaimStatusResponse,
    *,
    delimiters: Delimiters = DEFAULT_DELIMITERS,
    control_number: str = "1",
) -> str:
    """Build a 277-shaped response interchange from a resolved response.

    Demo output only: the segment set is a self-authored subset and the status,
    denial, and reject carriers are invented segments, so this is not conformant
    277 output and must not be presented as clearinghouse-ready EDI.
    """
    d = delimiters
    e = d.element

    def seg(*elements: str) -> str:
        return e.join(elements) + d.segment

    st_control = control_number.rjust(4, "0")

    body: list[str] = []
    body.append(seg("ST", "277", st_control))
    # BHT02 = 08 marks a status response in this demo subset.
    body.append(
        seg("BHT", "0010", "08", response.submitter_reference, "20260727", "1200")
    )
    if response.trace_number:
        body.append(seg("TRN", "2", response.trace_number))

    body.append(seg("HL", "1", "", "20", "1"))
    body.append(seg("NM1", "PR", "2", inquiry.payer_name or "SYNTHETIC PAYER"))

    body.append(seg("HL", "2", "1", "21", "1"))
    body.append(seg("NM1", "1P", "1", inquiry.provider.last_name or "PROVIDER"))

    body.append(seg("HL", "3", "2", "22", "0"))
    body.append(
        seg(
            "NM1",
            "IL",
            "1",
            inquiry.subscriber.last_name or "SUBSCRIBER",
            inquiry.subscriber.first_name,
        )
    )

    for row in response.rows:
        body.append(seg("REF", "ZZ", row.claim_ref, "CLAIM"))
        body.append(
            seg(
                STATUS_SEGMENT,
                row.status.value,
                _amount(row.billed),
                _amount(row.paid),
                row.rationale,
            )
        )
        for code in row.denial_codes:
            rule = DENIAL_CODE_TABLE.get(code)
            body.append(seg(DENIAL_SEGMENT, code, rule.description if rule else ""))
        if row.reject is not None:
            body.append(seg(REJECT_SEGMENT, row.reject.value, row.rationale))

    se_count = len(body) + 1
    body.append(seg("SE", str(se_count), st_control))

    isa = build_isa(d, control_number)
    gs = seg(
        "GS",
        "HN",
        "PAYER",
        "COPILOTPA",
        "20260727",
        "1200",
        control_number,
        "X",
        "DEMOSUBSET",
    )
    ge = seg("GE", "1", control_number)
    iea = seg("IEA", "1", control_number.rjust(9, "0"))

    return isa + d.segment + gs + "".join(body) + ge + iea


def _amount(value: Decimal | None) -> str:
    """Render a monetary element, or an empty element when not applicable."""
    return "" if value is None else f"{value:.2f}"


def answer_276(
    interchange: str,
    *,
    delimiters: Delimiters = DEFAULT_DELIMITERS,
    control_number: str = "1",
) -> tuple[ClaimStatusResponse, str]:
    """Parse a 276 inquiry, resolve it, and emit the 277-shaped response."""
    inquiry = parse_276_inquiry(interchange)
    response = resolve_claim_status(inquiry)
    return response, build_277_response(
        inquiry, response, delimiters=delimiters, control_number=control_number
    )
