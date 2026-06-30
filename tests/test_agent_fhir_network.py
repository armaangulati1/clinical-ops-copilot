"""Network integration: prior-auth agent fuses live FHIR facts with provenance."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from agent.approval_store import InMemoryApprovalStore
from agent.audit import InMemoryAuditTrail, get_case_history
from agent.config import load_config
from agent.executor import ActionExecutor
from agent.gate import ApprovalGate
from agent.llm import StubPlanner
from agent.mcp_host import StdioMcpHost
from agent.workflow import run_case_with_gate
from schemas.approval import AuditEventType, WorkflowStatus
from schemas.cases import Case
from schemas.seed_data import POLICIES

PROJECT_ROOT = Path(__file__).resolve().parents[1]

DEMO_PATIENT_ID = "78748"
HAPI_SKIP = "local HAPI FHIR server not reachable"


def _fhir_base_url() -> str:
    return os.environ.get("FHIR_BASE_URL", "http://localhost:8080/fhir").rstrip("/")


def _hapi_reachable() -> bool:
    try:
        response = httpx.get(f"{_fhir_base_url()}/metadata", timeout=2.0)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
@pytest.mark.network
@pytest.mark.skipif(not _hapi_reachable(), reason=HAPI_SKIP)
async def test_agent_uses_live_fhir_a1c_with_audit_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLINICAL_DATA_SOURCE", "fhir")
    monkeypatch.setenv("FHIR_BASE_URL", _fhir_base_url())
    monkeypatch.setenv("EXTRACTOR_BACKEND", "stub")

    policy = POLICIES["t2d"]
    case = Case(
        case_id="case-095",
        clinical_note=(
            "Endocrinology prior-auth request for semaglutide. "
            "Patient has type 2 diabetes; structured labs are in the EHR. "
            "Free-text note intentionally omits numeric A1C and BMI values."
        ),
        payer_policy=policy,
        drug=policy.drug,
        condition=policy.condition,
        patient_id=DEMO_PATIENT_ID,
    )
    config = load_config(PROJECT_ROOT)
    audit = InMemoryAuditTrail()
    store = InMemoryApprovalStore()
    host = await StdioMcpHost.connect(config)
    gate = ApprovalGate(
        store,
        audit,
        ActionExecutor(host, audit),
        confidence_threshold=0.8,
    )

    try:
        result = await run_case_with_gate(
            case,
            host,
            StubPlanner(),
            gate,
            config=config,
        )
    finally:
        await host.close()

    assert result.status == WorkflowStatus.PENDING_APPROVAL
    assert result.decision.action.value == "submit"
    assert result.approval_id is not None

    pending = store.get(result.approval_id)
    assert pending is not None
    assert pending.extraction.extraction.a1c_percent == 6.72
    provenance = pending.extraction.field_provenance["a1c_percent"]
    assert provenance.startswith("FHIR Observation 4548-4")
    assert "effective 2026-03-03" in provenance

    history = get_case_history(case.case_id, audit)
    provenance_events = [
        event
        for event in history
        if event.event_type == AuditEventType.FIELD_PROVENANCE
    ]
    assert provenance_events
    audit_provenance = provenance_events[0].payload["field_provenance"]
    assert audit_provenance["a1c_percent"].startswith("FHIR Observation 4548-4")
