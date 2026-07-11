"""Synthetic X12 278 REQUEST encoder.

This encoder is a *demo fixture synthesizer*: it turns one of the repo's
synthetic prior-auth cases (Synthea/HAPI-derived, no PHI) into a spec-shaped
278 (005010X217 subset) request. It exists so fixtures round-trip through the
real parser and so the eval wire-in can measure decision agreement across the
EDI boundary. It is a demo synthesizer, not real-world EDI tooling.

Two fields are demo simplifications, documented in edi/README.md:
* The full clinical narrative is inlined across MSG segments (a real 278 would
  reference supporting documentation as an attachment via PWK/275).
* The requested drug name and condition text are carried verbatim in REF
  segments tagged in REF03, so the same downstream policy lookup (keyed on the
  exact drug + condition strings) runs unchanged.
"""

from __future__ import annotations

import re

from edi.tokenizer import Delimiters
from schemas.cases import Case

# X12 MSG01 free-form message text maximum length.
_MSG_MAX_LEN = 264

# Minimal condition -> ICD-10-CM principal diagnosis code map for the three
# synthetic policy families. Used only for a realistic HI segment; the decision
# path keys on the condition string carried in REF, not on this code.
_CONDITION_ICD10 = {
    "rheumatoid arthritis": "M06.9",
    "type 2 diabetes": "E11.9",
    "chronic migraine": "G43.709",
}

_PATIENT_RE = re.compile(r"Patient:\s*(?P<name>[A-Za-z ]+?),\s*age", re.IGNORECASE)

DEFAULT_DELIMITERS = Delimiters(
    element="*",
    component=">",
    repetition="^",
    segment="~",
)


def build_isa(delimiters: Delimiters, control_number: str) -> str:
    """Build a fixed-width 005010 ISA header (106 chars incl. terminator)."""
    fields = [
        "00",  # ISA01 authorization info qualifier
        " " * 10,  # ISA02
        "00",  # ISA03 security info qualifier
        " " * 10,  # ISA04
        "ZZ",  # ISA05
        "COPILOTPA".ljust(15),  # ISA06 sender id
        "ZZ",  # ISA07
        "PAYER".ljust(15),  # ISA08 receiver id
        "260711",  # ISA09 date YYMMDD (synthetic)
        "1200",  # ISA10 time
        delimiters.repetition,  # ISA11
        "00501",  # ISA12 version
        control_number.rjust(9, "0"),  # ISA13
        "0",  # ISA14 ack requested
        "P",  # ISA15 usage indicator (P/T; synthetic)
        delimiters.component,  # ISA16 component separator
    ]
    return "ISA" + delimiters.element + delimiters.element.join(fields)


def _condition_code(condition: str) -> str:
    key = condition.strip().lower()
    for name, code in _CONDITION_ICD10.items():
        if name in key or key in name:
            return code
    return "R69"  # illness, unspecified (synthetic fallback)


def _patient_name(clinical_note: str) -> tuple[str, str]:
    match = _PATIENT_RE.search(clinical_note)
    if not match:
        return "PATIENT", ""
    parts = match.group("name").strip().split()
    if len(parts) == 1:
        return parts[0].upper(), ""
    return parts[-1].upper(), " ".join(parts[:-1]).upper()


def _chunk_note(note: str) -> list[str]:
    return [note[i : i + _MSG_MAX_LEN] for i in range(0, len(note), _MSG_MAX_LEN)]


def encode_278_request(
    case: Case,
    *,
    delimiters: Delimiters = DEFAULT_DELIMITERS,
    control_number: str = "1",
) -> str:
    """Encode a synthetic case into a 278 (005010X217 subset) request string."""
    d = delimiters
    e = d.element
    c = d.component

    def seg(*elements: str) -> str:
        return e.join(elements) + d.segment

    last, first = _patient_name(case.clinical_note)
    icd10 = _condition_code(case.condition)

    st_control = control_number.rjust(4, "0")

    # Transaction body (ST .. SE); SE count is filled in after assembly.
    body: list[str] = []
    body.append(seg("ST", "278", st_control, "005010X217"))
    body.append(seg("BHT", "0007", "13", case.case_id, "20260711", "1200"))

    # 2000A information source (payer)
    body.append(seg("HL", "1", "", "20", "1"))
    body.append(seg("NM1", "PR", "2", "SYNTHETIC PAYER", "", "", "", "", "PI", "PAYER"))

    # 2000B information receiver (requesting provider)
    body.append(seg("HL", "2", "1", "21", "1"))
    body.append(seg("NM1", "1P", "1", "PROVIDER", "", "", "", "", "XX", "1999999984"))

    # 2000C subscriber (patient)
    body.append(seg("HL", "3", "2", "22", "1"))
    if case.patient_id:
        body.append(
            seg("NM1", "IL", "1", last, first, "", "", "", "MI", case.patient_id)
        )
    else:
        body.append(seg("NM1", "IL", "1", last, first))

    # 2000E service / event level
    body.append(seg("HL", "4", "3", "EV", "0"))
    body.append(seg("UM", "HS", "I", "3"))
    body.append(seg("DTP", "472", "D8", "20260711"))
    body.append(seg("HI", f"ABK{c}{icd10}"))
    # Demo carriers for the exact policy-lookup keys.
    body.append(seg("REF", "ZZ", case.drug, "DRUG"))
    body.append(seg("REF", "ZZ", case.condition, "CONDITION"))
    for chunk in _chunk_note(case.clinical_note):
        body.append(seg("MSG", chunk))

    # SE trailer: segment count includes ST and SE.
    se_count = len(body) + 1
    body.append(seg("SE", str(se_count), st_control))

    isa = build_isa(d, control_number)
    gs = seg(
        "GS",
        "HI",
        "COPILOTPA",
        "PAYER",
        "20260711",
        "1200",
        control_number,
        "X",
        "005010X217",
    )
    ge = seg("GE", "1", control_number)
    iea = seg("IEA", "1", control_number.rjust(9, "0"))

    return isa + d.segment + gs + "".join(body) + ge + iea
