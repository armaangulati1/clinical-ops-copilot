"""Tests for case and label loaders."""

from pathlib import Path

import pytest

from schemas.loader import load_case_file


def test_load_case_file_rejects_embedded_labels(tmp_path: Path) -> None:
    case_path = tmp_path / "case-999.json"
    case_path.write_text(
        '{"case_id":"case-999","clinical_note":"' + ("x" * 60) + '",'
        '"correct_action":"submit","drug":"Humira","condition":"ra",'
        '"payer_policy":{"drug":"Humira","condition":"ra",'
        '"required_criteria_fields":["a"],"rules":"rule text long enough here"}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="must not contain label key"):
        load_case_file(case_path)
