"""Tests for graceful FHIR degradation when the server is unreachable."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from agent.approval_store import InMemoryApprovalStore
from agent.audit import InMemoryAuditTrail, get_case_history
from agent.config import load_config
from agent.executor import ActionExecutor
from agent.fhir_resilience import (
    FHIR_UNAVAILABLE_FALLBACK_REASON,
    is_fhir_unavailable_error,
)
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


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _complete_note_extraction() -> ExtractionResult:
    return ExtractionResult(
        extraction=Extraction(
            a1c_percent=8.2,
            metformin_trial_months=6,
            bmi=32.0,
            diabetes_duration_years=3,
        ),
        field_confidence={
            "a1c_percent": 0.95,
            "metformin_trial_months": 0.95,
            "bmi": 0.95,
            "diabetes_duration_years": 0.95,
        },
        evidence={
            "a1c_percent": "A1C: 8.2%",
            "metformin_trial_months": "Metformin trial: 6 months",
            "bmi": "BMI: 32.0",
            "diabetes_duration_years": "Diabetes duration: 3 years",
        },
    )


def test_is_fhir_unavailable_error_detects_transport_failures() -> None:
    assert is_fhir_unavailable_error(
        RuntimeError("FHIR transport error: connection refused")
    )
    assert is_fhir_unavailable_error(ConnectionError("connection refused"))
    assert not is_fhir_unavailable_error(ValueError("invalid patient_id"))


@pytest.mark.anyio
async def test_fhir_down_falls_back_to_note_only_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    policy = POLICIES["t2d"]
    case = Case(
        case_id="case-094",
        clinical_note=(
            "Type 2 diabetes prior-auth packet with documented criteria in the note. "
            "A1C: 8.2%. Metformin trial: 6 months. BMI: 32.0. "
            "Diabetes duration: 3 years."
        ),
        payer_policy=policy,
        drug=policy.drug,
        condition=policy.condition,
        patient_id="78748",
    )
    host = MockMcpHost(
        extraction_payload=_complete_note_extraction().model_dump(mode="json"),
        policy_payload=policy.model_dump(mode="json"),
        fhir_unavailable=True,
    )
    config = load_config(PROJECT_ROOT)

    with caplog.at_level(logging.WARNING, logger="agent.fhir_resilience"):
        result = await run_case(case, host, StubPlanner(), config=config)

    assert result.decision.action.value == "submit"
    assert result.extraction.extraction.a1c_percent == 8.2
    assert result.run_log.fhir_fallback is not None
    assert result.run_log.fhir_fallback["reason"] == FHIR_UNAVAILABLE_FALLBACK_REASON
    assert any(
        "FHIR server unavailable after retries" in record.message
        for record in caplog.records
    )


@pytest.mark.anyio
async def test_fhir_down_fallback_recorded_in_audit_trail() -> None:
    policy = POLICIES["t2d"]
    case = Case(
        case_id="case-093",
        clinical_note=(
            "Type 2 diabetes prior-auth with complete note-based criteria. "
            "A1C: 8.2%. Metformin trial: 6 months. BMI: 32.0. "
            "Diabetes duration: 3 years."
        ),
        payer_policy=policy,
        drug=policy.drug,
        condition=policy.condition,
        patient_id="78748",
    )
    host = MockMcpHost(
        extraction_payload=_complete_note_extraction().model_dump(mode="json"),
        policy_payload=policy.model_dump(mode="json"),
        fhir_unavailable=True,
    )
    audit = InMemoryAuditTrail()
    gate = ApprovalGate(
        InMemoryApprovalStore(),
        audit,
        ActionExecutor(host, audit),
        confidence_threshold=0.8,
    )

    await run_case_with_gate(case, host, StubPlanner(), gate)

    history = get_case_history(case.case_id, audit)
    fallback_events = [
        event for event in history if event.event_type == AuditEventType.FHIR_FALLBACK
    ]
    assert len(fallback_events) == 1
    assert fallback_events[0].payload["reason"] == FHIR_UNAVAILABLE_FALLBACK_REASON
