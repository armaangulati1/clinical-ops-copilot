"""Guard: the 270/271 and 276/277 demos carry no company or real-code content.

These are generic, self-authored eligibility and claim-status demos. They must
never carry a real company name, a real payer/vendor name, or content from a
real X12 code list (service type codes, eligibility/benefit codes, reject reason
codes, claim status category or claim status codes). This guard scans the source,
fixtures, golden data, and the README so a real-world identifier cannot slip in.

The blocked terms are not written here, and they are not written in any guard.
All three name guards load the same SHA-256 digests from
``tests/vendor_blocklist.digests.txt``, so there is exactly one place the list
lives and no plaintext copy of it exists in the repo. See
``tests/company_name_guard.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edi.claim_status_277 import CLAIM_STORE, answer_276
from edi.eligibility_271 import COVERAGE_TABLE, SERVICE_TYPES, answer_270
from edi.invented_segments import BENEFIT_SEGMENT, REJECT_SEGMENT, STATUS_SEGMENT
from tests.company_name_guard import scan_paths

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EDI = PROJECT_ROOT / "edi"
FIXTURES_270 = EDI / "fixtures" / "x270"
FIXTURES_276 = EDI / "fixtures" / "x276"

# Globs rather than a hand list: a seventh eligibility/claim-status module added
# later must not be silently unscanned.
SCANNED_FILES = [
    *sorted(EDI.glob("*27[0167]*.py")),
    *sorted(EDI.glob("eligibility_*.py")),
    *sorted(EDI.glob("claim_status_*.py")),
    EDI / "invented_segments.py",
    EDI / "README.md",
    *sorted(FIXTURES_270.glob("*")),
    *sorted(FIXTURES_276.glob("*")),
]

# Real X12 segments this demo deliberately does NOT emit, because each carries an
# externally maintained code list: AAA (reject reasons), EB (eligibility/benefit
# information), STC (claim status). Invented carriers are used instead.
REAL_CODE_LIST_SEGMENTS = ["AAA*", "EB*", "STC*"]


def test_no_forbidden_names() -> None:
    offenders = scan_paths(SCANNED_FILES, PROJECT_ROOT)
    assert not offenders, "blocked term(s) present: " + "; ".join(offenders)


def test_scanned_surface_is_present() -> None:
    present = [p for p in SCANNED_FILES if p.exists()]
    assert len(present) >= 20


@pytest.mark.parametrize("segment", REAL_CODE_LIST_SEGMENTS)
def test_fixtures_avoid_real_code_list_segments(segment: str) -> None:
    for path in [*sorted(FIXTURES_270.glob("*.270")), *sorted(FIXTURES_276.glob("*"))]:
        if path.suffix not in (".270", ".276"):
            continue
        for token in path.read_text(encoding="utf-8").split("~"):
            assert not token.startswith(segment), f"{segment} in {path}"


@pytest.mark.parametrize("segment", REAL_CODE_LIST_SEGMENTS)
def test_generated_responses_avoid_real_code_list_segments(segment: str) -> None:
    interchanges = [
        answer_270((FIXTURES_270 / f"{stem}.270").read_text(encoding="utf-8"))[1]
        for stem in ("multi_service_types", "inactive_plan", "unknown_member")
    ] + [
        answer_276((FIXTURES_276 / f"{stem}.276").read_text(encoding="utf-8"))[1]
        for stem in ("batch_three", "unknown_claim")
    ]
    for interchange in interchanges:
        for token in interchange.split("~"):
            assert not token.startswith(segment), segment


def test_inquiry_fixtures_use_only_self_authored_service_types() -> None:
    for path in sorted(FIXTURES_270.glob("*.270")):
        for token in path.read_text(encoding="utf-8").split("~"):
            if token.startswith("EQ*") and len(token) > 3:
                assert token.split("*")[1].startswith("SRV-"), path


def test_generated_271_uses_only_self_authored_benefit_codes() -> None:
    for stem in ("multi_service_types", "inactive_plan", "not_covered_service"):
        _, interchange = answer_270(
            (FIXTURES_270 / f"{stem}.270").read_text(encoding="utf-8")
        )
        for token in interchange.split("~"):
            if token.startswith(f"{BENEFIT_SEGMENT}*"):
                assert token.split("*")[2].startswith("EB-"), stem
            if token.startswith(f"{REJECT_SEGMENT}*"):
                assert token.split("*")[1].startswith("RJ-"), stem


def test_generated_277_uses_only_self_authored_status_codes() -> None:
    for stem in ("batch_three", "pending_review", "unknown_claim"):
        _, interchange = answer_276(
            (FIXTURES_276 / f"{stem}.276").read_text(encoding="utf-8")
        )
        for token in interchange.split("~"):
            if token.startswith(f"{STATUS_SEGMENT}*"):
                assert token.split("*")[1].startswith("CS-"), stem
            if token.startswith(f"{REJECT_SEGMENT}*"):
                assert token.split("*")[1].startswith("RJ-"), stem


def test_code_tables_are_self_authored() -> None:
    assert all(key.startswith("SRV-") for key in SERVICE_TYPES)
    assert all(key.startswith("MBR-") for key in COVERAGE_TABLE)
    assert all(key.startswith("CLM-") for key in CLAIM_STORE)


def test_synthetic_member_and_claim_ids_are_obviously_fake() -> None:
    # No 9-digit member ids or claim numbers that could read as real identifiers.
    for key in [*COVERAGE_TABLE, *CLAIM_STORE]:
        assert not key.isdigit(), key
