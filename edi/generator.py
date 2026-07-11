"""X12 278 RESPONSE generator.

Emits a valid-shaped 278 (005010X217 subset) health-care-services-review
RESPONSE from the agent's :class:`schemas.decisions.Decision`, echoing the
request context (submitter reference, patient, provider, service). The
decision-to-HCR mapping lives in ``edi.decision_map``.

Scope: this is a demo/portfolio generator, not HIPAA-certified EDI tooling.
The response carries no clinical narrative and no PHI beyond the identifiers
already present in the request context.
"""

from __future__ import annotations

from edi.decision_map import map_decision
from edi.encoder import DEFAULT_DELIMITERS, build_isa
from edi.parser import Request278
from edi.tokenizer import Delimiters
from schemas.decisions import Decision


def build_278_response(
    decision: Decision,
    request: Request278,
    *,
    delimiters: Delimiters = DEFAULT_DELIMITERS,
    control_number: str = "1",
    review_id: str = "RV0000001",
) -> str:
    """Build a 278 response interchange from a decision and its request."""
    d = delimiters
    e = d.element
    c = d.component
    mapping = map_decision(decision.action)

    def seg(*elements: str) -> str:
        return e.join(elements) + d.segment

    st_control = control_number.rjust(4, "0")

    body: list[str] = []
    body.append(seg("ST", "278", st_control, "005010X217"))
    # BHT02 = 11 marks a response to a prior request.
    body.append(
        seg("BHT", "0007", "11", request.submitter_reference, "20260711", "1200")
    )

    # Echo the payer as information source.
    body.append(seg("HL", "1", "", "20", "1"))
    body.append(
        seg(
            "NM1",
            "PR",
            "2",
            request.payer_name or "SYNTHETIC PAYER",
            "",
            "",
            "",
            "",
            "PI",
            "PAYER",
        )
    )

    # Echo the requesting provider.
    body.append(seg("HL", "2", "1", "21", "1"))
    if request.provider.npi:
        body.append(
            seg(
                "NM1",
                "1P",
                "1",
                request.provider.last_name or "PROVIDER",
                request.provider.first_name,
                "",
                "",
                "",
                "XX",
                request.provider.npi,
            )
        )
    else:
        body.append(seg("NM1", "1P", "1", request.provider.last_name or "PROVIDER"))

    # Echo the subscriber / patient.
    body.append(seg("HL", "3", "2", "22", "1"))
    if request.patient.member_id:
        body.append(
            seg(
                "NM1",
                "IL",
                "1",
                request.patient.last_name or "PATIENT",
                request.patient.first_name,
                "",
                "",
                "",
                "MI",
                request.patient.member_id,
            )
        )
    else:
        body.append(
            seg(
                "NM1",
                "IL",
                "1",
                request.patient.last_name or "PATIENT",
                request.patient.first_name,
            )
        )

    # Service / event level with the review determination.
    body.append(seg("HL", "4", "3", "EV", "0"))
    body.append(
        seg(
            "UM",
            request.request_category or "HS",
            request.certification_type or "I",
            request.service_type or "3",
        )
    )
    for code in request.diagnosis_codes:
        body.append(seg("HI", f"ABK{c}{code}"))
    # HCR: action code + review id; reason code left blank (no A3 in this subset).
    body.append(seg("HCR", mapping.action_code, review_id, ""))
    body.append(seg("MSG", f"{mapping.action_label}: {mapping.reason}"))
    if decision.missing_fields:
        body.append(seg("MSG", "Missing fields: " + ", ".join(decision.missing_fields)))

    se_count = len(body) + 1
    body.append(seg("SE", str(se_count), st_control))

    isa = build_isa(d, control_number)
    gs = seg(
        "GS",
        "HI",
        "PAYER",
        "COPILOTPA",
        "20260711",
        "1200",
        control_number,
        "X",
        "005010X217",
    )
    ge = seg("GE", "1", control_number)
    iea = seg("IEA", "1", control_number.rjust(9, "0"))

    return isa + d.segment + gs + "".join(body) + ge + iea
