"""CI-safe tests for fixture generation (Pillow only, no tesseract)."""

from __future__ import annotations

import json
from pathlib import Path

from ocr.generate_fixtures import _LETTERS, generate


def test_generate_produces_expected_files(tmp_path: Path) -> None:
    gts = generate(tmp_path)
    assert len(gts) == len(_LETTERS) == 12
    for gt in gts:
        assert (tmp_path / gt.image).exists()
        assert (tmp_path / gt.image).stat().st_size > 0
    gt_file = tmp_path / "ground_truth.json"
    assert gt_file.exists()
    data = json.loads(gt_file.read_text())
    assert len(data) == 12
    assert {*data[0]} == {
        "image",
        "case_id",
        "patient_name",
        "decision",
        "drug",
        "condition",
        "auth_number",
        "decision_date",
        "valid_through",
    }


def test_generation_is_deterministic(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    generate(a)
    generate(b)
    for gt in _LETTERS:
        assert (a / gt.image).read_bytes() == (b / gt.image).read_bytes()
    assert (a / "ground_truth.json").read_bytes() == (
        b / "ground_truth.json"
    ).read_bytes()


def test_decision_mix_is_varied() -> None:
    decisions = {gt.decision for gt in _LETTERS}
    assert decisions == {"APPROVED", "DENIED", "PENDED"}
    approved = [gt for gt in _LETTERS if gt.decision == "APPROVED"]
    # Approved letters carry an auth number and a valid-through date.
    assert all(gt.auth_number and gt.valid_through for gt in approved)
    # Non-approved letters carry neither.
    non_approved = [gt for gt in _LETTERS if gt.decision != "APPROVED"]
    assert all(
        gt.auth_number is None and gt.valid_through is None for gt in non_approved
    )
