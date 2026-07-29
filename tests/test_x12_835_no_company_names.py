"""Guard: the 835 denial-triage demo names no company, vendor, or real code.

This is a generic, self-authored "denial triage demo". It must never carry a
real company name, a real payer or clearinghouse name, a leftover demo persona,
or any real CARC/RARC adjustment reason code. This guard scans the 835 source,
fixtures, golden data, and README section so a real-world identifier cannot slip
in.

The blocked terms are not written here. They are loaded as SHA-256 digests from
``tests/vendor_blocklist.digests.txt``; see ``tests/company_name_guard.py`` for
why, and for what that does and does not protect against.
"""

from __future__ import annotations

from pathlib import Path

from tests.company_name_guard import scan_paths

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EDI = PROJECT_ROOT / "edi"

# Files that make up the 835 denial-triage demo surface. Globs, not a hand list,
# so a module or fixture added later cannot be silently unscanned.
SCANNED_FILES = [
    *sorted(EDI.glob("*835*.py")),
    EDI / "denial_triage.py",
    EDI / "eval_triage.py",
    EDI / "README.md",
    *sorted((EDI / "fixtures" / "x835").glob("*")),
]


def test_no_forbidden_names() -> None:
    offenders = scan_paths(SCANNED_FILES, PROJECT_ROOT)
    assert not offenders, "blocked term(s) present: " + "; ".join(offenders)


def test_scanned_surface_is_present() -> None:
    # sanity: the guard is actually scanning real files, not an empty set
    present = [p for p in SCANNED_FILES if p.exists()]
    assert len(present) >= 10


def test_no_real_carc_rarc_style_codes_in_fixtures() -> None:
    # real CARC codes are bare integers in CAS segments; this demo uses only
    # self-authored DR-* codes carried in an invented DRC segment.
    for path in sorted((EDI / "fixtures" / "x835").glob("*.835")):
        text = path.read_text(encoding="utf-8")
        assert "CAS*" not in text, f"real-style CAS segment in {path}"
        for token in text.split("~"):
            if token.startswith("DRC*"):
                code = token.split("*")[1]
                assert code.startswith("DR-"), f"non self-authored denial code: {code}"
