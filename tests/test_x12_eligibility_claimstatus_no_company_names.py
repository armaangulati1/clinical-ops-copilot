"""Guard: the 270/271 and 276/277 demos carry no company or real-code content.

These are generic, self-authored eligibility and claim-status demos. They must
never carry a real company name, a real payer/vendor name, or content from a
real X12 code list (service type codes, eligibility/benefit codes, reject reason
codes, claim status category or claim status codes). This guard scans the source,
fixtures, golden data, and the README so a real-world identifier cannot slip in.

The forbidden-name list is imported from the existing 835 guard rather than
duplicated, so there is exactly one place that list lives.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from edi.claim_status_277 import CLAIM_STORE, answer_276
from edi.eligibility_271 import COVERAGE_TABLE, SERVICE_TYPES, answer_270
from tests.test_x12_835_no_company_names import FORBIDDEN

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EDI = PROJECT_ROOT / "edi"
FIXTURES_270 = EDI / "fixtures" / "x270"
FIXTURES_276 = EDI / "fixtures" / "x276"

SCANNED_FILES = [
    EDI / "x12_270.py",
    EDI / "eligibility_271.py",
    EDI / "eval_eligibility.py",
    EDI / "x12_276.py",
    EDI / "claim_status_277.py",
    EDI / "eval_claim_status.py",
    EDI / "README.md",
    *sorted(FIXTURES_270.glob("*.270")),
    *sorted(FIXTURES_276.glob("*.276")),
    FIXTURES_270 / "golden.json",
    FIXTURES_276 / "golden.json",
]

# Real X12 segments this demo deliberately does NOT emit, because each carries an
# externally maintained code list: AAA (reject reasons), EB (eligibility/benefit
# information), STC (claim status). Invented carriers are used instead.
REAL_CODE_LIST_SEGMENTS = ["AAA*", "EB*", "STC*"]


def _demo_text() -> dict[Path, str]:
    return {
        p: p.read_text(encoding="utf-8").lower() for p in SCANNED_FILES if p.exists()
    }


@pytest.mark.parametrize("needle", FORBIDDEN)
def test_no_forbidden_names(needle: str) -> None:
    hits = [str(p) for p, text in _demo_text().items() if needle in text]
    assert not hits, f"forbidden token {needle!r} found in: {hits}"


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
            if token.startswith("EBC*"):
                assert token.split("*")[2].startswith("EB-"), stem
            if token.startswith("RJC*"):
                assert token.split("*")[1].startswith("RJ-"), stem


def test_generated_277_uses_only_self_authored_status_codes() -> None:
    for stem in ("batch_three", "pending_review", "unknown_claim"):
        _, interchange = answer_276(
            (FIXTURES_276 / f"{stem}.276").read_text(encoding="utf-8")
        )
        for token in interchange.split("~"):
            if token.startswith("CSI*"):
                assert token.split("*")[1].startswith("CS-"), stem
            if token.startswith("RJC*"):
                assert token.split("*")[1].startswith("RJ-"), stem


def test_code_tables_are_self_authored() -> None:
    assert all(key.startswith("SRV-") for key in SERVICE_TYPES)
    assert all(key.startswith("MBR-") for key in COVERAGE_TABLE)
    assert all(key.startswith("CLM-") for key in CLAIM_STORE)


def test_synthetic_member_and_claim_ids_are_obviously_fake() -> None:
    # No 9-digit member ids or claim numbers that could read as real identifiers.
    for key in [*COVERAGE_TABLE, *CLAIM_STORE]:
        assert not key.isdigit(), key
