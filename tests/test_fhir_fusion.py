"""Offline tests for FHIR + note fusion and fallback behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.approval_store import InMemoryApprovalStore
from agent.audit import InMemoryAuditTrail, get_case_history
from agent.config import load_config
from agent.executor import ActionExecutor
from agent.gate import ApprovalGate
from agent.llm import StubPlanner
from agent.mcp_host import MockMcpHost
from agent.runner import run_case
from agent.workflow import run_case_with_gate
from schemas.approval import AuditEventType
from schemas.cases import Case
from schemas.extraction import Extraction
from schemas.extraction_result import ExtractionResult
from schemas.seed_data import POLICIES

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "tests/fixtures/fhir_patient_78748.json"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _fixture_payload() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _sparse_note_extraction() -> ExtractionResult:
    """Note missing several T2D fields so FHIR must supply them."""
    return ExtractionResult(
        extraction=Extraction(),
        field_confidence={},
        needs_review=[],
        evidence={},
    )


def _note_with_only_duration() -> ExtractionResult:
    """Note supplies one field FHIR also has; FHIR should win when present."""
    return ExtractionResult(
        extraction=Extraction(diabetes_duration_years=10),
        field_confidence={"diabetes_duration_years": 0.9},
        evidence={"diabetes_duration_years": "Patient has had diabetes for ten years."},
    )


@pytest.mark.anyio
async def test_fhir_fusion_fills_missing_fields_from_mock_mcp() -> None:
    fixture = _fixture_payload()
    policy = POLICIES["t2d"]
    case = Case(
        case_id="case-098",
        clinical_note=(
            "Brief endocrinology follow-up for type 2 diabetes. "
            "Considering GLP-1 therapy; structured labs in EHR."
        ),
        payer_policy=policy,
        drug=policy.drug,
        condition=policy.condition,
        patient_id=str(fixture["patient_id"]),
    )
    host = MockMcpHost(
        extraction_payload=_sparse_note_extraction().model_dump(mode="json"),
        policy_payload=policy.model_dump(mode="json"),
        fhir_observations=fixture["observations"],  # type: ignore[arg-type]
        fhir_conditions=fixture["conditions"],  # type: ignore[arg-type]
        fhir_medications=fixture["medications"],  # type: ignore[arg-type]
    )
    config = load_config(PROJECT_ROOT)
    result = await run_case(
        case,
        host,
        StubPlanner(),
        config=config,
    )

    assert result.decision.action.value == "submit"
    assert result.decision.missing_fields == []
    assert result.extraction.extraction.a1c_percent == 6.72
    assert result.extraction.field_provenance["a1c_percent"].startswith(
        "FHIR Observation 4548-4"
    )


@pytest.mark.anyio
async def test_fallback_uses_note_when_fhir_lacks_required_field() -> None:
    fixture = _fixture_payload()
    policy = POLICIES["t2d"]
    case = Case(
        case_id="case-097",
        clinical_note=(
            "Type 2 diabetes patient with documented ten-year disease duration. "
            "Structured FHIR chart available for labs and medications."
        ),
        payer_policy=policy,
        drug=policy.drug,
        condition=policy.condition,
        patient_id=str(fixture["patient_id"]),
    )
    host = MockMcpHost(
        extraction_payload=_note_with_only_duration().model_dump(mode="json"),
        policy_payload=policy.model_dump(mode="json"),
        fhir_observations=fixture["observations"],  # type: ignore[arg-type]
        fhir_conditions=[],
        fhir_medications=fixture["medications"],  # type: ignore[arg-type]
    )
    audit = InMemoryAuditTrail()
    store = InMemoryApprovalStore()
    gate = ApprovalGate(
        store,
        audit,
        ActionExecutor(host, audit),
        confidence_threshold=0.8,
    )

    workflow = await run_case_with_gate(case, host, StubPlanner(), gate)
    assert workflow.approval_id is not None
    pending = store.get(workflow.approval_id)
    assert pending is not None
    result_extraction = pending.extraction

    assert result_extraction.extraction.diabetes_duration_years == 10
    assert result_extraction.field_provenance["diabetes_duration_years"] == "note"
    assert result_extraction.field_provenance["a1c_percent"].startswith(
        "FHIR Observation 4548-4"
    )

    history = get_case_history(case.case_id, audit)
    provenance_events = [
        event
        for event in history
        if event.event_type == AuditEventType.FIELD_PROVENANCE
    ]
    assert provenance_events
    assert provenance_events[0].payload["field_provenance"]["a1c_percent"].startswith(
        "FHIR Observation 4548-4"
    )
    assert (
        provenance_events[0].payload["field_provenance"]["diabetes_duration_years"]
        == "note"
    )


@pytest.mark.anyio
async def test_missing_fhir_and_note_triggers_request_more_info() -> None:
    policy = POLICIES["t2d"]
    case = Case(
        case_id="case-096",
        clinical_note=(
            "Sparse diabetes note without numeric criteria documented in free text. "
            "No structured supplemental data expected for this test case."
        ),
        payer_policy=policy,
        drug=policy.drug,
        condition=policy.condition,
        patient_id="78748",
    )
    host = MockMcpHost(
        extraction_payload=_sparse_note_extraction().model_dump(mode="json"),
        policy_payload=policy.model_dump(mode="json"),
        fhir_observations={},
        fhir_conditions=[],
        fhir_medications=[],
    )
    audit = InMemoryAuditTrail()
    gate = ApprovalGate(
        InMemoryApprovalStore(),
        audit,
        ActionExecutor(host, audit),
        confidence_threshold=0.8,
    )

    result = await run_case_with_gate(case, host, StubPlanner(), gate)

    assert result.decision.action.value == "request-more-info"
    assert set(result.decision.missing_fields) == set(policy.required_criteria_fields)
