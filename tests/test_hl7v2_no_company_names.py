"""Guard: the HL7 v2 package leaks no company names.

Follows the prebill/278 precedent. Every artifact in ``hl7v2/`` (source,
fixtures, goldens, README) must use only invented facilities and synthetic
patients. This test fails if any real company name -- a portfolio target
company or a real health-IT / EHR vendor -- appears anywhere in the package.
"""

from __future__ import annotations

import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "hl7v2"

# Case-insensitive, word-boundary denylist. Kept to unambiguous company tokens
# so ordinary clinical vocabulary never trips it.
FORBIDDEN = [
    # Real EHR / health-IT vendors.
    "epic systems",
    "cerner",
    "meditech",
    "athenahealth",
    "allscripts",
    "veradigm",
    "nextgen healthcare",
    "mirth",
    "redox",
    "particle health",
    "health gorilla",
    "1up health",
    "medplum",
    # Portfolio target companies.
    "commure",
    "athelas",
    "palantir",
    "assort",
    "tennr",
    "triomics",
    "veeva",
    "smartsheet",
    "simbie",
    "northslope",
    "qventus",
    "silna",
    "abridge",
    "notable",
    "anthropic",
    "openai",
]

SCANNED_SUFFIXES = {".py", ".hl7", ".json", ".md", ".txt"}


def _iter_files() -> list[Path]:
    return [
        path
        for path in PACKAGE.rglob("*")
        if path.is_file()
        and path.suffix in SCANNED_SUFFIXES
        and "__pycache__" not in path.parts
    ]


def test_no_forbidden_company_names() -> None:
    patterns = {
        term: re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE) for term in FORBIDDEN
    }
    offenders: list[str] = []
    for path in _iter_files():
        text = path.read_text(encoding="utf-8")
        for term, pattern in patterns.items():
            if pattern.search(text):
                offenders.append(f"{path.name}: {term!r}")
    assert not offenders, f"company name(s) leaked: {offenders}"


def test_guard_scans_the_expected_surface() -> None:
    scanned = {path.suffix for path in _iter_files()}
    # Source, fixtures, and goldens must all be in scope.
    assert ".py" in scanned
    assert ".hl7" in scanned
    assert ".json" in scanned
