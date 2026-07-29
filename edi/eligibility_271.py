"""Deterministic 271 eligibility responder over a synthetic coverage table.

Given a parsed :class:`~edi.x12_270.EligibilityInquiry`, this module resolves a
benefit outcome per requested service type from a small, transparent,
self-authored coverage table, and emits a 271-shaped response interchange. There
is no scoring model and no LLM: every outcome is a pure function of the coverage
table and the inquiry, so the output is fully reproducible offline.

Invented code systems (honest scope):

* ``SRV-*`` service types are a demo vocabulary authored for this project. They
  are NOT the real externally maintained service type codes that appear in a
  production 270 ``EQ01``.
* ``EB-*`` benefit outcomes are likewise self-authored. They are NOT the real
  eligibility/benefit information codes of a production 271, and the table below
  models no real payer's benefit design.
* ``RJ-*`` reject reasons are self-authored and carried in an invented ``ZRJC``
  segment, and benefit outcomes in an invented ``ZEBC`` segment. Real 270/271
  pairs carry this content in ``AAA`` and ``EB`` segments using externally
  maintained code lists; none of that content is reproduced here. Both carrier
  IDs are four characters, and an X12 segment ID is two or three, so neither can
  collide with a real segment. See :mod:`edi.invented_segments` for the rule and
  the evidence behind it.

Role framing: a 271 response is issued by the payer side. This module
**simulates the payer side** for demo purposes, showing what a coverage response
would look like given a synthetic member record. It is demo output only, not a
real coverage determination and not a clearinghouse integration.

Benefit outcome classes:

* ``EB-ACTIVE-COVERED`` - active coverage, cost share reported.
* ``EB-AUTH-REQUIRED`` - covered, but the plan requires prior authorization
  before the service.
* ``EB-DEDUCTIBLE-UNMET`` - covered, but the member's deductible is unmet, so
  the member is responsible for the allowed amount.
* ``EB-NOT-COVERED`` - the requested service type is not a benefit of this plan.
* ``EB-INACTIVE`` - the member's plan is not active, so no service type can be
  reported as covered.

When several conditions hold for one service type, the **most restrictive**
outcome wins (inactive > not-covered > auth-required > deductible-unmet >
active-covered), mirroring the conservative precedence the 835 denial-triage
layer uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from edi.encoder import DEFAULT_DELIMITERS, build_isa
from edi.invented_segments import BENEFIT_SEGMENT, REJECT_SEGMENT
from edi.tokenizer import Delimiters
from edi.x12_270 import EligibilityInquiry, parse_270_inquiry

# BENEFIT_SEGMENT ("ZEBC") and REJECT_SEGMENT ("ZRJC") are defined once in
# edi.invented_segments, which also documents why a four-character carrier ID
# cannot collide with a real X12 segment.


class BenefitOutcome(StrEnum):
    """Self-authored benefit outcome for one requested service type."""

    ACTIVE_COVERED = "EB-ACTIVE-COVERED"
    AUTH_REQUIRED = "EB-AUTH-REQUIRED"
    DEDUCTIBLE_UNMET = "EB-DEDUCTIBLE-UNMET"
    NOT_COVERED = "EB-NOT-COVERED"
    INACTIVE = "EB-INACTIVE"


class RejectReason(StrEnum):
    """Self-authored, inquiry-level reject reasons (invented, not real AAA)."""

    MEMBER_NOT_FOUND = "RJ-MEMBER-NOT-FOUND"
    DOB_MISMATCH = "RJ-DOB-MISMATCH"


# Restrictiveness ordering: a higher rank overrides a lower one for the same
# service type. Mirrors the conservative precedence of the denial-triage layer.
_PRECEDENCE: dict[BenefitOutcome, int] = {
    BenefitOutcome.ACTIVE_COVERED: 0,
    BenefitOutcome.DEDUCTIBLE_UNMET: 1,
    BenefitOutcome.AUTH_REQUIRED: 2,
    BenefitOutcome.NOT_COVERED: 3,
    BenefitOutcome.INACTIVE: 4,
}


@dataclass(frozen=True)
class ServiceBenefit:
    """One plan benefit: cost share plus the flags the resolver reads."""

    copay: Decimal = Decimal("0")
    deductible_remaining: Decimal = Decimal("0")
    prior_auth_required: bool = False


@dataclass(frozen=True)
class MemberCoverage:
    """A synthetic member record in the demo coverage table."""

    member_id: str
    last_name: str
    birth_date: str  # CCYYMMDD
    plan_name: str
    plan_active: bool
    benefits: dict[str, ServiceBenefit] = field(default_factory=dict)


# Self-authored service type vocabulary. NOT real X12 service type codes.
SERVICE_TYPES: dict[str, str] = {
    "SRV-MEDICAL": "General medical benefit",
    "SRV-PHARMACY": "Outpatient pharmacy benefit",
    "SRV-SPECIALIST": "Specialist office visit",
    "SRV-IMAGING": "Advanced diagnostic imaging",
    "SRV-BEHAVIORAL": "Behavioral health benefit",
}

# Single source of truth for the synthetic coverage table, rendered as a table
# in edi/README.md. Every member, plan, and amount here is invented.
COVERAGE_TABLE: dict[str, MemberCoverage] = {
    "MBR-1001": MemberCoverage(
        member_id="MBR-1001",
        last_name="ALPHA",
        birth_date="19850214",
        plan_name="DEMO PLAN A",
        plan_active=True,
        benefits={
            "SRV-MEDICAL": ServiceBenefit(copay=Decimal("25.00")),
            "SRV-SPECIALIST": ServiceBenefit(copay=Decimal("45.00")),
            "SRV-IMAGING": ServiceBenefit(
                copay=Decimal("75.00"), prior_auth_required=True
            ),
        },
    ),
    "MBR-1002": MemberCoverage(
        member_id="MBR-1002",
        last_name="BRAVO",
        birth_date="19910730",
        plan_name="DEMO PLAN B",
        plan_active=True,
        benefits={
            "SRV-MEDICAL": ServiceBenefit(
                copay=Decimal("0.00"), deductible_remaining=Decimal("400.00")
            ),
            "SRV-PHARMACY": ServiceBenefit(
                copay=Decimal("15.00"), prior_auth_required=True
            ),
        },
    ),
    "MBR-1003": MemberCoverage(
        member_id="MBR-1003",
        last_name="CHARLIE",
        birth_date="19770101",
        plan_name="DEMO PLAN C",
        plan_active=False,
        benefits={
            "SRV-MEDICAL": ServiceBenefit(copay=Decimal("30.00")),
            "SRV-PHARMACY": ServiceBenefit(copay=Decimal("20.00")),
        },
    ),
}


@dataclass(frozen=True)
class BenefitRow:
    """The resolved outcome for one requested service type."""

    service_type: str
    outcome: BenefitOutcome
    copay: Decimal | None = None
    deductible_remaining: Decimal | None = None
    rationale: str = ""


@dataclass(frozen=True)
class EligibilityResponse:
    """Everything the 271 generator needs, resolved and typed."""

    submitter_reference: str
    member_id: str
    plan_name: str = ""
    rows: list[BenefitRow] = field(default_factory=list)
    reject: RejectReason | None = None
    reject_note: str = ""

    @property
    def rejected(self) -> bool:
        return self.reject is not None


def resolve_eligibility(inquiry: EligibilityInquiry) -> EligibilityResponse:
    """Resolve every requested service type against the coverage table."""
    member_id = inquiry.require_member_key()
    coverage = COVERAGE_TABLE.get(member_id)

    if coverage is None:
        return EligibilityResponse(
            submitter_reference=inquiry.submitter_reference,
            member_id=member_id,
            reject=RejectReason.MEMBER_NOT_FOUND,
            reject_note="Member id not present in the demo coverage table.",
        )

    inquiry_dob = inquiry.subscriber.birth_date
    if inquiry_dob and inquiry_dob != coverage.birth_date:
        # Never resolve coverage against a member whose identity did not match.
        return EligibilityResponse(
            submitter_reference=inquiry.submitter_reference,
            member_id=member_id,
            plan_name=coverage.plan_name,
            reject=RejectReason.DOB_MISMATCH,
            reject_note="Subscriber date of birth does not match the member record.",
        )

    rows = [
        _resolve_service_type(coverage, service_type)
        for service_type in inquiry.service_types
    ]
    return EligibilityResponse(
        submitter_reference=inquiry.submitter_reference,
        member_id=member_id,
        plan_name=coverage.plan_name,
        rows=rows,
    )


def _resolve_service_type(coverage: MemberCoverage, service_type: str) -> BenefitRow:
    """Apply the restrictiveness precedence for one requested service type."""
    candidates: list[BenefitOutcome] = []
    benefit = coverage.benefits.get(service_type)

    if not coverage.plan_active:
        candidates.append(BenefitOutcome.INACTIVE)
    if benefit is None:
        candidates.append(BenefitOutcome.NOT_COVERED)
    else:
        if benefit.prior_auth_required:
            candidates.append(BenefitOutcome.AUTH_REQUIRED)
        if benefit.deductible_remaining > Decimal("0"):
            candidates.append(BenefitOutcome.DEDUCTIBLE_UNMET)
        candidates.append(BenefitOutcome.ACTIVE_COVERED)

    winner = max(candidates, key=lambda outcome: _PRECEDENCE[outcome])
    copay = benefit.copay if benefit is not None else None
    deductible = benefit.deductible_remaining if benefit is not None else None
    if winner in (BenefitOutcome.INACTIVE, BenefitOutcome.NOT_COVERED):
        # No cost share is meaningful when nothing is payable.
        copay = None
        deductible = None
    return BenefitRow(
        service_type=service_type,
        outcome=winner,
        copay=copay,
        deductible_remaining=deductible,
        rationale=_rationale(winner, service_type, coverage),
    )


def _rationale(
    outcome: BenefitOutcome, service_type: str, coverage: MemberCoverage
) -> str:
    """Deterministic, transparent explanation for one resolved outcome."""
    label = SERVICE_TYPES.get(service_type, "Unrecognized service type")
    if outcome is BenefitOutcome.INACTIVE:
        return f"{coverage.plan_name} is not active; no benefit can be reported."
    if outcome is BenefitOutcome.NOT_COVERED:
        return f"{label} is not a benefit of {coverage.plan_name}."
    if outcome is BenefitOutcome.AUTH_REQUIRED:
        return f"{label} is covered but requires prior authorization."
    if outcome is BenefitOutcome.DEDUCTIBLE_UNMET:
        return f"{label} is covered; member deductible is not yet met."
    return f"{label} is active with the reported copay."


def build_271_response(
    inquiry: EligibilityInquiry,
    response: EligibilityResponse,
    *,
    delimiters: Delimiters = DEFAULT_DELIMITERS,
    control_number: str = "1",
) -> str:
    """Build a 271-shaped response interchange from a resolved response.

    Demo output only: the segment set is a self-authored subset and the benefit
    and reject carriers are invented segments, so this is not conformant 271
    output and must not be presented as clearinghouse-ready EDI.
    """
    d = delimiters
    e = d.element

    def seg(*elements: str) -> str:
        return e.join(elements) + d.segment

    st_control = control_number.rjust(4, "0")

    body: list[str] = []
    body.append(seg("ST", "271", st_control))
    # BHT02 = 11 marks a response to a prior request (mirrors the 278 layer).
    body.append(
        seg("BHT", "0022", "11", response.submitter_reference, "20260727", "1200")
    )

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
            "",
            "",
            "",
            "MI",
            response.member_id,
        )
    )
    if inquiry.service_date:
        body.append(seg("DTP", "472", "D8", inquiry.service_date))

    if response.reject is not None:
        body.append(seg(REJECT_SEGMENT, response.reject.value, response.reject_note))
    else:
        for row in response.rows:
            body.append(
                seg(
                    BENEFIT_SEGMENT,
                    row.service_type,
                    row.outcome.value,
                    _amount(row.copay),
                    _amount(row.deductible_remaining),
                    row.rationale,
                )
            )

    se_count = len(body) + 1
    body.append(seg("SE", str(se_count), st_control))

    isa = build_isa(d, control_number)
    gs = seg(
        "GS",
        "HB",
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


def answer_270(
    interchange: str,
    *,
    delimiters: Delimiters = DEFAULT_DELIMITERS,
    control_number: str = "1",
) -> tuple[EligibilityResponse, str]:
    """Parse a 270 inquiry, resolve it, and emit the 271-shaped response."""
    inquiry = parse_270_inquiry(interchange)
    response = resolve_eligibility(inquiry)
    return response, build_271_response(
        inquiry, response, delimiters=delimiters, control_number=control_number
    )
