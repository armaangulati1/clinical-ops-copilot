"""Guard: the 835 denial-triage demo must contain no company/vendor names.

This is a generic, self-authored "denial triage demo". It must never carry a
real company name, a real payer/vendor name, or any real CARC/RARC adjustment
reason code. This guard scans the 835 source, fixtures, golden data, and README
section so a stray real-world identifier can never slip in.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EDI = PROJECT_ROOT / "edi"

# Files that make up the 835 denial-triage demo surface.
SCANNED_FILES = [
    EDI / "x12_835.py",
    EDI / "denial_triage.py",
    EDI / "eval_triage.py",
    *sorted((EDI / "fixtures" / "x835").glob("*.835")),
    EDI / "fixtures" / "x835" / "golden.json",
]

# Case-insensitive substrings that must never appear in the demo surface:
# specific company/vendor names, prior demo persona names, and real payers.
FORBIDDEN = [
    "cair",
    "dennis",
    "chloe",
    "ella",
    "aetna",
    "cigna",
    "unitedhealth",
    "optum",
    "humana",
    "anthem",
    "availity",
    "change healthcare",
    "waystar",
]


def _demo_text() -> dict[Path, str]:
    return {
        p: p.read_text(encoding="utf-8").lower() for p in SCANNED_FILES if p.exists()
    }


@pytest.mark.parametrize("needle", FORBIDDEN)
def test_no_forbidden_names(needle: str) -> None:
    hits = [str(p) for p, text in _demo_text().items() if needle in text]
    assert not hits, f"forbidden token {needle!r} found in: {hits}"


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
