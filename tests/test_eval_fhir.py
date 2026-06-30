"""Tests for the FHIR-backed eval harness."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent.llm import StubPlanner
from agent.mcp_host import MockMcpHost
from evals.fhir.dataset import (
    FHIR_LABELS_PATH,
    load_fhir_eval_dataset,
)
from evals.fhir.runner import FhirEvalResults, build_fhir_eval_config
from evals.models import EvalResults
from tests.test_fhir_fusion import _fixture_payload

PROJECT_ROOT = Path(__file__).resolve().parents[1]
HAPI_SKIP = "local HAPI FHIR server not reachable"


def _hapi_reachable() -> bool:
    try:
        response = httpx.get("http://localhost:8080/fhir/metadata", timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_fhir_labels_loaded_only_inside_evals_package() -> None:
    labels_path = PROJECT_ROOT / FHIR_LABELS_PATH
    payload = json.loads(labels_path.read_text(encoding="utf-8"))
    assert "labels" in payload
    assert "case-049" in payload["labels"]

    offenders: list[str] = []
    for path in PROJECT_ROOT.rglob("*.py"):
        rel = path.relative_to(PROJECT_ROOT)
        if rel.parts[0] in {"agent", "servers", "ui"}:
            source = path.read_text(encoding="utf-8")
            if "evals/fhir/labels.json" in source or "fhir/labels.json" in source:
                offenders.append(str(rel))
    assert offenders == [], f"FHIR labels referenced outside evals: {offenders}"


def test_fhir_eval_host_config_uses_stdio_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "CLINICAL_DATA_URL",
        "https://clinical-data-mcp.fly.dev/mcp",
    )
    monkeypatch.setenv("CLINICAL_DATA_AUTH_TOKEN", "fly-bearer-token")
    config = build_fhir_eval_config(PROJECT_ROOT)
    assert config.clinical_data_url is None
    assert config.clinical_data_auth_token is None


def test_load_fhir_eval_dataset_pairs_cases_with_labels() -> None:
    entries, manifest = load_fhir_eval_dataset(PROJECT_ROOT)
    assert len(entries) == 12
    assert manifest.get("labels_confirmed") is True
    for entry in entries:
        assert entry.case.patient_id
        assert entry.label.correct_action


@pytest.mark.anyio
async def test_fhir_eval_runner_produces_valid_results_object() -> None:
    fixture = _fixture_payload()
    entries, _ = load_fhir_eval_dataset(PROJECT_ROOT)
    subset = [entry for entry in entries if entry.case.case_id == "case-057"]

    def host_factory(entry: object) -> MockMcpHost:
        from schemas.loader import DatasetEntry

        assert isinstance(entry, DatasetEntry)
        return MockMcpHost(
            extraction_payload={
                "extraction": {},
                "field_confidence": {},
                "needs_review": [],
                "evidence": {},
                "field_provenance": {},
                "review_threshold": 0.75,
            },
            policy_payload=entry.case.payer_policy.model_dump(mode="json"),
            fhir_observations=fixture["observations"],
            fhir_conditions=fixture["conditions"],
            fhir_medications=fixture["medications"],
        )

    from evals.runner import run_dataset_eval

    case_results = await run_dataset_eval(
        subset,
        StubPlanner(),
        host_factory=host_factory,
    )
    from evals.aggregate import build_eval_results

    fhir_eval = build_eval_results(subset, case_results, planner_model="stub")
    results = FhirEvalResults(
        integrity=fhir_eval.integrity,
        labels_confirmed=False,
        patient_ids_by_case={"case-057": "78748"},
        fhir=fhir_eval,
        caveats=["offline mock test"],
    )
    validated = EvalResults.model_validate(results.fhir.model_dump(mode="json"))
    assert validated.n_cases == 1
    assert validated.classification.macro_f1 >= 0.0


@pytest.mark.anyio
@pytest.mark.network
@pytest.mark.skipif(not _hapi_reachable(), reason=HAPI_SKIP)
async def test_fhir_eval_cli_against_hapi() -> None:
    from evals.fhir.runner import run_fhir_eval_command

    await run_fhir_eval_command(PROJECT_ROOT, use_live_planner=False)
    results_path = PROJECT_ROOT / "evals/results/fhir.json"
    summary_path = PROJECT_ROOT / "evals/results/fhir_summary.md"
    assert results_path.exists()
    assert summary_path.exists()
    payload = json.loads(results_path.read_text(encoding="utf-8"))
    assert payload["fhir"]["n_cases"] == 12
    assert "classification" in payload["fhir"]
    assert payload["fhir"]["classification"]["macro_f1"] >= 0.0
