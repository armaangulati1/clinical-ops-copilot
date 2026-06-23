"""Network tests for the agentic prior-auth extractor (requires ANTHROPIC_API_KEY)."""

from __future__ import annotations

import os

import pytest

from schemas.extraction import Extraction
from schemas.extraction_result import ExtractionResult
from schemas.loader import load_case_file
from schemas.seed_data import POLICIES
from servers.clinical_data.priorauth_extractor.pipeline import run_pipeline

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
RA_NOTE = load_case_file(PROJECT_ROOT / "data/cases/case-001.json").clinical_note
MISSING_DAS28_NOTE = (
    "Outpatient rheumatology prior-auth request for adalimumab (Humira). "
    "Patient: Jamie Ortiz, age 50. Diagnosis: rheumatoid arthritis (ICD-10 M06.9). "
    "Disease duration: 10 months. Failed conventional DMARDs: 2. "
    "Methotrexate trial: 14 weeks. Requesting Humira."
)


def _require_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set")


@pytest.mark.network
def test_real_extractor_populates_ra_fields() -> None:
    _require_api_key()
    result = run_pipeline(RA_NOTE, policy=POLICIES["ra"])
    validated = ExtractionResult.model_validate(result.model_dump(mode="json"))
    extraction = Extraction.model_validate(validated.extraction.model_dump(mode="json"))
    assert extraction.das28_score is not None
    assert extraction.patient_name is not None
    assert validated.field_confidence["das28_score"] >= 0.0


@pytest.mark.network
def test_real_extractor_flags_missing_required_field() -> None:
    _require_api_key()
    result = run_pipeline(MISSING_DAS28_NOTE, policy=POLICIES["ra"])
    assert "das28_score" in result.needs_review
    assert result.field_confidence["das28_score"] < result.review_threshold
