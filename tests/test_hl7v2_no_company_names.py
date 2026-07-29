"""Guard: the HL7 v2 package names no real company.

Every artifact in ``hl7v2/`` (source, fixtures, goldens, README) must use only
invented facilities and synthetic patients. This test fails if any blocked term
appears anywhere in the package.

The blocked terms are not written here. They are loaded as SHA-256 digests from
``tests/vendor_blocklist.digests.txt``; see ``tests/company_name_guard.py`` for
why, and for what that does and does not protect against.
"""

from __future__ import annotations

from pathlib import Path

from tests.company_name_guard import count_hits, scan_paths

PACKAGE = Path(__file__).resolve().parents[1] / "hl7v2"

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
    offenders = scan_paths(_iter_files(), PACKAGE.parent)
    assert not offenders, "blocked term(s) present: " + "; ".join(offenders)


def test_guard_scans_the_expected_surface() -> None:
    scanned = {path.suffix for path in _iter_files()}
    # Source, fixtures, and goldens must all be in scope.
    assert ".py" in scanned
    assert ".hl7" in scanned
    assert ".json" in scanned


def test_guard_would_catch_a_planted_name() -> None:
    """A guard nobody has ever seen fail is not known to work.

    A real blocked term is reconstructed from the local plaintext blocklist when
    it is present, and from the committed example placeholders otherwise, then
    planted in a synthetic HL7-shaped string. Nothing is written to disk and no
    term is echoed on failure.
    """
    from tests.company_name_guard import (
        DIGESTS,
        EXAMPLE_BLOCKLIST,
        LOCAL_BLOCKLIST,
        digest,
        read_plaintext_terms,
    )

    source = LOCAL_BLOCKLIST if LOCAL_BLOCKLIST.exists() else EXAMPLE_BLOCKLIST
    terms = [t for t in read_plaintext_terms(source) if digest(t) in DIGESTS]
    assert terms, "no plaintext term available to plant"

    for term in terms:
        planted = f"MSH|^~\\&|SENDING_APP|{term.upper()}|RECV|FAC|20260728||ADT^A01"
        assert count_hits(planted) >= 1, "guard missed a planted term"
    # And it stays quiet on the package's own vocabulary.
    assert count_hits("MSH|^~\\&|ADT^A01|OBX|synthetic patient|invented clinic") == 0
