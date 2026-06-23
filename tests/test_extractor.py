"""Tests for chart extraction stub."""

import json
from pathlib import Path

from schemas.extraction import Extraction
from schemas.extraction_result import ExtractionResult
from schemas.loader import load_case_file
from servers.clinical_data.extractor import (
    ChartExtractor,
    extract,
    get_prior_auth_extractor,
)


def test_extract_phase1_note_validates_against_extraction_schema() -> None:
    case = load_case_file(Path("data/cases/case-001.json"))
    result = extract(case.clinical_note)
    assert isinstance(result, ExtractionResult)
    validated = Extraction.model_validate(result.extraction.model_dump(mode="json"))
    assert validated.patient_name == "Jordan Blake"
    assert validated.das28_score == 4.8
    assert result.needs_review == []


def test_chart_extractor_stub_is_marked_and_usable() -> None:
    extractor = ChartExtractor()
    result = extractor.extract("Patient: Alex Mercer, age 42.")
    assert isinstance(result, ExtractionResult)
    assert result.extraction.age == 42


def test_prior_auth_extractor_defaults_to_stub() -> None:
    extractor = get_prior_auth_extractor()
    assert isinstance(extractor, ChartExtractor)


def test_stub_returns_high_confidence_and_no_review() -> None:
    case = load_case_file(Path("data/cases/case-001.json"))
    result = extract(case.clinical_note)
    assert result.field_confidence["das28_score"] == 1.0
    assert result.needs_review == []


def test_extract_chart_from_file_path(tmp_path: Path) -> None:
    chart = tmp_path / "note.txt"
    chart.write_text(
        json.loads(Path("data/cases/case-001.json").read_text())["clinical_note"],
        encoding="utf-8",
    )
    text = chart.read_text(encoding="utf-8")
    result = extract(text)
    assert result.extraction.failed_dmards == 2
