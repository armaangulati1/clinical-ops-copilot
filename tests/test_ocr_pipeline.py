"""Tesseract-dependent OCR pipeline tests.

Marked ``ocr`` and excluded from the CI gate (``pytest -m "not network"`` is
the gate; CI runs additionally exclude ``ocr`` and ``browser``). They also
self-skip when the tesseract binary is not on PATH, so a local run without
tesseract degrades gracefully instead of erroring.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ocr.eval_ocr import evaluate
from ocr.generate_fixtures import FIXTURES_DIR, generate
from ocr.reader import OcrError, read_image, read_letter

pytestmark = [
    pytest.mark.ocr,
    pytest.mark.skipif(
        shutil.which("tesseract") is None,
        reason="tesseract binary not installed",
    ),
]


def test_read_image_extracts_text_from_fixture() -> None:
    text = read_image(FIXTURES_DIR / "letter_01.png")
    assert "Case ID" in text
    assert "PA-2026-0042" in text


def test_read_letter_roundtrip_on_clean_fixture() -> None:
    rec = read_letter(FIXTURES_DIR / "letter_01.png")
    assert rec.case_id == "PA-2026-0042"
    assert rec.decision == "APPROVED"
    assert rec.auth_number == "AUTH-8871245"


def test_eval_meets_documented_accuracy_floor() -> None:
    # The committed fixtures score 100%; assert a conservative floor so the
    # test is a regression guard, not a brittle exact-match.
    result = evaluate()
    assert result.overall_total == 96
    assert result.overall_accuracy >= 0.90


def test_missing_image_raises_structured_error() -> None:
    with pytest.raises(OcrError):
        read_image(FIXTURES_DIR / "does_not_exist.png")


def test_empty_image_yields_unknown_record(tmp_path: Path) -> None:
    from PIL import Image

    blank = tmp_path / "blank.png"
    Image.new("RGB", (400, 200), "white").save(blank)
    rec = read_letter(blank)
    assert rec.decision == "UNKNOWN"
    assert rec.case_id is None


def test_non_image_file_raises_structured_error(tmp_path: Path) -> None:
    bad = tmp_path / "not_an_image.png"
    bad.write_text("this is not a PNG")
    with pytest.raises(OcrError):
        read_image(bad)


def test_regeneration_matches_committed_fixtures(tmp_path: Path) -> None:
    generate(tmp_path)
    for name in ("letter_01.png", "letter_11.png"):
        assert (tmp_path / name).read_bytes() == (FIXTURES_DIR / name).read_bytes()
