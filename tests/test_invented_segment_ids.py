"""Regression guard for the invented carrier segments and the claims made about them.

Three defects are locked out here, each one found in review of the 270/271 and
276/277 branch before it shipped:

1. ``CSI`` was used as the 277 status carrier and asserted, in four places, to be
   "not a real X12 segment". It **is** one: "Claim Status Information",
   transaction set 260. See :func:`test_csi_is_never_emitted_as_a_segment_id`.
2. Any carrier the demo invents must be impossible to confuse with a real X12
   segment *by construction*, not by somebody having checked a directory. See
   :func:`test_every_invented_carrier_cannot_be_an_x12_segment_id`.
3. The phrase "all four core HIPAA transaction families" is false. HIPAA covers
   at least 270/271, 276/277, 278, 820, 834, 835, 837 and 275, and this repo
   implements demo subsets of four of them, which is not the same statement. See
   :func:`test_no_false_hipaa_coverage_claim`.
"""

from __future__ import annotations

import re
from pathlib import Path

from edi.claim_status_277 import DENIAL_SEGMENT, answer_276
from edi.eligibility_271 import answer_270
from edi.invented_segments import (
    DISPLACED_REAL_SEGMENTS,
    INVENTED_CARRIERS,
    LEGACY_THREE_CHAR_CARRIERS,
    X12_SEGMENT_ID_MAX_LEN,
    cannot_be_an_x12_segment_id,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EDI = PROJECT_ROOT / "edi"
FIXTURES_270 = EDI / "fixtures" / "x270"
FIXTURES_276 = EDI / "fixtures" / "x276"

# Every prose surface in the repo that could make a claim about the X12 standard.
# This was a hand-written list of `edi/*.py` plus two READMEs, which meant the
# retracted wording could reappear in tests/, docs/, hl7v2/, agent/ or any other
# package and the guard would never see it. A claim is a claim wherever it lives.
#
# Vendored trees are out of scope: this guards claims *this repo* makes, and a
# JDK's licence texts are not ours to police. Dot-directories (.venv, .java,
# .git) and tool caches are skipped for the same reason.
_SKIP_DIRS = {"__pycache__", "node_modules", "synthea", "pgdata", "site-packages"}
_CLAIM_SUFFIXES = {".py", ".md"}


def _claim_surface() -> list[Path]:
    return sorted(
        path
        for path in PROJECT_ROOT.rglob("*")
        if path.is_file()
        and path.suffix in _CLAIM_SUFFIXES
        and not any(part in _SKIP_DIRS or part.startswith(".") for part in path.parts)
    )


CLAIM_SURFACE = _claim_surface()

# A sample of real X12 segment IDs, including the one this repo got wrong. Every
# entry is a genuine segment identifier; the point of the sample is that all of
# them are two or three characters, which is what makes a four-character
# invented carrier safe.
REAL_X12_SEGMENT_IDS = [
    "CSI",  # Claim Status Information (transaction set 260) - the missed one
    "AAA",  # Request Validation
    "EB",  # Eligibility or Benefit Information
    "STC",  # Status Information
    "CAS",  # Claims Adjustment
    "ISA",
    "GS",
    "ST",
    "SE",
    "GE",
    "IEA",
    "BHT",
    "HL",
    "NM1",
    "DMG",
    "DTP",
    "EQ",
    "REF",
    "TRN",
    "CLP",
    "SVC",
    "BPR",
    "UM",
    "HI",
    "MSG",
]

# The retracted claim, and the marker that proves a file quoting it also carries
# the correction. Any file allowed to contain the retracted wording must also
# name the transaction set that disproves it.
RETRACTED_CLAIM = re.compile(r"not\s+(?:a\s+)?real\s+x12\s+segments?", re.IGNORECASE)
RETRACTION_MARKER = "transaction set 260"

# Wordings of the false HIPAA-coverage claim. HIPAA names more transaction
# families than this repo implements, so "all four" is wrong in any phrasing.
# As with the retracted segment claim, the false wording is allowed to survive
# where it is being corrected rather than asserted, and a file that quotes it
# must carry the correction: the actual HIPAA transaction list. No file exempts
# itself here, including this one.
FALSE_HIPAA_CORRECTION_MARKER = "820, 834"

FALSE_HIPAA_CLAIMS = [
    re.compile(r"all\s+four\s+core\s+hipaa", re.IGNORECASE),
    re.compile(r"all\s+(?:the\s+)?core\s+hipaa\s+transaction", re.IGNORECASE),
    re.compile(r"all\s+four\s+hipaa\s+transaction", re.IGNORECASE),
    re.compile(r"four\s+core\s+hipaa\s+transaction\s+famil", re.IGNORECASE),
    re.compile(r"all\s+hipaa\s+transaction\s+famil", re.IGNORECASE),
]


def _generated_interchanges() -> list[str]:
    """Every 271 and 277 interchange the demo can produce from its fixtures."""
    return [
        answer_270(path.read_text(encoding="utf-8"))[1]
        for path in sorted(FIXTURES_270.glob("*.270"))
        if path.stat().st_size and not path.name.startswith("malformed_")
    ] + [
        answer_276(path.read_text(encoding="utf-8"))[1]
        for path in sorted(FIXTURES_276.glob("*.276"))
        if path.stat().st_size and not path.name.startswith("malformed_")
    ]


def _segment_ids(interchange: str) -> set[str]:
    """Pull the segment identifier out of every segment in an interchange."""
    return {
        segment.split("*")[0].strip()
        for segment in interchange.split("~")
        if segment.strip()
    }


# --------------------------------------------------------------------------
# Blocker 1: the CSI collision
# --------------------------------------------------------------------------


def test_csi_is_never_emitted_as_a_segment_id() -> None:
    """``CSI`` is a real X12 segment, so the demo must never emit it."""
    interchanges = _generated_interchanges()
    assert interchanges, "no interchanges generated; the guard would pass vacuously"
    for interchange in interchanges:
        assert "CSI" not in _segment_ids(interchange)


def test_csi_is_not_registered_as_an_invented_carrier() -> None:
    """``CSI`` must not be claimed as invented, in either carrier registry."""
    assert "CSI" not in INVENTED_CARRIERS
    assert "CSI" not in LEGACY_THREE_CHAR_CARRIERS


def test_every_invented_carrier_cannot_be_an_x12_segment_id() -> None:
    """The structural guarantee: each invented carrier is too long to be real."""
    assert INVENTED_CARRIERS, "registry is empty; the guard would pass vacuously"
    for carrier in INVENTED_CARRIERS:
        assert len(carrier) == 4, carrier
        assert cannot_be_an_x12_segment_id(carrier), carrier


def test_real_x12_segment_ids_are_two_or_three_characters() -> None:
    """The premise the guarantee rests on, asserted rather than assumed.

    A four-character ID is safe only because no real segment ID is that long.
    """
    for segment_id in REAL_X12_SEGMENT_IDS:
        assert len(segment_id) <= X12_SEGMENT_ID_MAX_LEN, segment_id
        assert not cannot_be_an_x12_segment_id(segment_id), segment_id


def test_collision_is_impossible_between_invented_and_real_ids() -> None:
    """The two premises combined: the sets cannot intersect, on length alone."""
    assert INVENTED_CARRIERS.isdisjoint(REAL_X12_SEGMENT_IDS)
    assert INVENTED_CARRIERS.isdisjoint(DISPLACED_REAL_SEGMENTS)
    shortest_invented = min(len(c) for c in INVENTED_CARRIERS)
    longest_real = max(len(s) for s in REAL_X12_SEGMENT_IDS)
    assert shortest_invented > longest_real


def test_generated_output_uses_the_invented_carriers() -> None:
    """Positive control: this guard can fail, so its passes mean something."""
    emitted: set[str] = set()
    for interchange in _generated_interchanges():
        emitted |= _segment_ids(interchange)
    assert emitted >= INVENTED_CARRIERS, INVENTED_CARRIERS - emitted


def test_generated_output_emits_no_displaced_real_segments() -> None:
    """The invented carriers exist so these real code-list segments stay unused."""
    for interchange in _generated_interchanges():
        assert DISPLACED_REAL_SEGMENTS.isdisjoint(_segment_ids(interchange))


def test_legacy_carrier_is_still_used_where_documented() -> None:
    """``DRC`` keeps its three-character ID; the docs must keep saying so."""
    assert DENIAL_SEGMENT in LEGACY_THREE_CHAR_CARRIERS
    assert DENIAL_SEGMENT not in INVENTED_CARRIERS


def test_retracted_claim_never_appears_without_its_correction() -> None:
    """A file may quote "not a real X12 segment" only while retracting it.

    The wording is what shipped the defect. It is allowed to survive as a
    documented correction, never as a live assertion, so any file containing it
    must also name transaction set 260, which is the proof it was wrong.
    """
    offenders = []
    for path in CLAIM_SURFACE:
        text = path.read_text(encoding="utf-8")
        if RETRACTED_CLAIM.search(text) and RETRACTION_MARKER not in text.lower():
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert not offenders, (
        "file(s) assert a segment is 'not a real X12 segment' without carrying "
        f"the correction ({RETRACTION_MARKER}): {offenders}"
    )


def test_retracted_claim_pattern_actually_matches() -> None:
    """Control: the pattern can fire, so a clean scan is real evidence.

    Its sibling HIPAA guard has always carried one of these. This one did not,
    which meant a typo in the regex would have turned every pass above into a
    silent vacuous pass.
    """
    for specimen in (
        "ZCSI is not a real X12 segment",
        "these are Not Real X12 Segments",
        "asserted it was not  a  real x12 segment",
    ):
        assert RETRACTED_CLAIM.search(specimen), specimen
    # And it stays quiet on prose that merely discusses real segments.
    for benign in (
        "CSI is a real X12 segment",
        "the demo emits no real X12 segments from the displaced set",
    ):
        assert not RETRACTED_CLAIM.search(benign), benign


def test_claim_surface_covers_more_than_the_edi_package() -> None:
    """The old hand-written surface could not see tests/, docs/ or other packages."""
    parents = {
        path.relative_to(PROJECT_ROOT).parts[0]
        for path in CLAIM_SURFACE
        if len(path.relative_to(PROJECT_ROOT).parts) > 1
    }
    assert {"edi", "tests", "hl7v2", "agent"} <= parents, parents
    assert len(CLAIM_SURFACE) >= 50


# --------------------------------------------------------------------------
# Blocker 3: the false HIPAA-coverage claim
# --------------------------------------------------------------------------


def test_no_false_hipaa_coverage_claim() -> None:
    """This repo implements four demo subsets, not "all" of anything HIPAA names."""
    offenders = []
    for path in CLAIM_SURFACE:
        text = path.read_text(encoding="utf-8")
        makes_claim = any(pattern.search(text) for pattern in FALSE_HIPAA_CLAIMS)
        if makes_claim and FALSE_HIPAA_CORRECTION_MARKER not in text:
            offenders.append(str(path.relative_to(PROJECT_ROOT)))
    assert not offenders, (
        "file(s) make a false HIPAA coverage claim without carrying the "
        f"correction ({FALSE_HIPAA_CORRECTION_MARKER}): {offenders}"
    )


def test_false_hipaa_claim_patterns_actually_match() -> None:
    """Control: the patterns above can fire, so a clean scan is real evidence."""
    specimen = "covers all four core HIPAA transaction families"
    assert any(pattern.search(specimen) for pattern in FALSE_HIPAA_CLAIMS)
