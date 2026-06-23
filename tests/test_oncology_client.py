"""Tests for ChartExtractor oncology API client and MCP tool."""

from __future__ import annotations

import json

import httpx
import pytest

from servers.clinical_data.oncology_client import extract_oncology_note
from servers.clinical_data.oncology_schema import ExtractionOutput, OncologyExtract

SAMPLE_ONCOLOGY_NOTE = (
    "Oncology follow-up: 67-year-old male with lung adenocarcinoma, stage IIIA, "
    "diagnosed 2023-10-09. ECOG 1. First-line pembrolizumab, carboplatin, pemetrexed. "
    "EGFR negative, PD-L1 positive."
)

MOCK_API_RESPONSE = {
    "extract": {
        "primary_site": "lung",
        "histology": "adenocarcinoma",
        "stage": "IIIA",
        "biomarkers": [
            {"name": "EGFR", "status": "negative"},
            {"name": "PD-L1", "status": "positive"},
        ],
        "ecog_performance_status": 1,
        "line_of_therapy": 1,
        "date_of_diagnosis": "2023-10-09",
        "treatment_regimen": ["pembrolizumab", "carboplatin", "pemetrexed"],
    },
    "fields": {},
    "needs_review": [],
    "review_threshold": 0.75,
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    "run_metrics": {"latency_ms": 10.0, "estimated_cost_usd": 0.0, "trace_id": None},
}


def test_oncology_schema_validates_sample_payload() -> None:
    result = ExtractionOutput.model_validate(MOCK_API_RESPONSE)
    assert result.extract.primary_site == "lung"


def test_extract_oncology_note_validates_mock_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/extract"
        body = json.loads(request.content.decode())
        assert body["text"] == SAMPLE_ONCOLOGY_NOTE
        return httpx.Response(200, json=MOCK_API_RESPONSE)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport, base_url="https://example.test") as client:
        result = extract_oncology_note(
            SAMPLE_ONCOLOGY_NOTE,
            base_url="https://example.test",
            http_client=client,
        )

    assert isinstance(result, ExtractionOutput)
    assert isinstance(result.extract, OncologyExtract)
    assert result.extract.histology == "adenocarcinoma"


@pytest.mark.network
def test_live_chartextract_api_returns_valid_oncology_extract() -> None:
    result = extract_oncology_note(SAMPLE_ONCOLOGY_NOTE)
    validated = ExtractionOutput.model_validate(result.model_dump(mode="json"))
    assert validated.extract.histology is not None
