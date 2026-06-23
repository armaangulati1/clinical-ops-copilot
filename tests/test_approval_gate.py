"""Approval gate safety tests (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.approval_store import InMemoryApprovalStore
from agent.audit import InMemoryAuditTrail, get_case_history
from agent.config import load_config
from agent.executor import ActionExecutor
from agent.gate import ApprovalGate
from agent.llm import StubPlanner
from agent.mcp_host import MockMcpHost
from agent.workflow import run_case_with_gate
from schemas.approval import AuditEventType, WorkflowStatus
from schemas.loader import load_case_file
from servers.clinical_data.extractor import extract

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _build_gate(host: MockMcpHost) -> ApprovalGate:
    audit = InMemoryAuditTrail()
    store = InMemoryApprovalStore()
    executor = ActionExecutor(host, audit)
    return ApprovalGate(store, audit, executor)


@pytest.mark.anyio
async def test_high_risk_decision_pauses_without_clinic_ops_side_effect() -> None:
    case = load_case_file(PROJECT_ROOT / "data/cases/case-001.json")
    extraction = extract(case.clinical_note)
    host = MockMcpHost(
        extraction_payload=extraction.model_dump(mode="json"),
        policy_payload=case.payer_policy.model_dump(mode="json"),
    )
    gate = _build_gate(host)

    result = await run_case_with_gate(
        case,
        host,
        StubPlanner(),
        gate,
        config=load_config(PROJECT_ROOT),
    )

    assert result.status == WorkflowStatus.PENDING_APPROVAL
    assert result.approval_id is not None
    assert host.clinic_ops_counters.get("create_task", 0) == 0


@pytest.mark.anyio
async def test_approve_executes_exactly_once() -> None:
    case = load_case_file(PROJECT_ROOT / "data/cases/case-001.json")
    extraction = extract(case.clinical_note)
    host = MockMcpHost(
        extraction_payload=extraction.model_dump(mode="json"),
        policy_payload=case.payer_policy.model_dump(mode="json"),
    )
    gate = _build_gate(host)

    workflow = await run_case_with_gate(case, host, StubPlanner(), gate)
    assert workflow.approval_id is not None

    await gate.approve(workflow.approval_id, reviewer="alice")
    assert host.clinic_ops_counters.get("create_task", 0) == 1

    await gate.approve(workflow.approval_id, reviewer="alice")
    assert host.clinic_ops_counters.get("create_task", 0) == 1


@pytest.mark.anyio
async def test_reject_never_executes_action() -> None:
    case = load_case_file(PROJECT_ROOT / "data/cases/case-001.json")
    extraction = extract(case.clinical_note)
    host = MockMcpHost(
        extraction_payload=extraction.model_dump(mode="json"),
        policy_payload=case.payer_policy.model_dump(mode="json"),
    )
    gate = _build_gate(host)

    workflow = await run_case_with_gate(case, host, StubPlanner(), gate)
    assert workflow.approval_id is not None

    await gate.reject(workflow.approval_id, reviewer="bob")
    assert host.clinic_ops_counters.get("create_task", 0) == 0

    with pytest.raises(ValueError):
        await gate.approve(workflow.approval_id, reviewer="bob")


@pytest.mark.anyio
async def test_get_case_history_orders_full_trail() -> None:
    case = load_case_file(PROJECT_ROOT / "data/cases/case-001.json")
    extraction = extract(case.clinical_note)
    host = MockMcpHost(
        extraction_payload=extraction.model_dump(mode="json"),
        policy_payload=case.payer_policy.model_dump(mode="json"),
    )
    audit = InMemoryAuditTrail()
    store = InMemoryApprovalStore()
    gate = ApprovalGate(store, audit, ActionExecutor(host, audit))

    workflow = await run_case_with_gate(case, host, StubPlanner(), gate)
    assert workflow.approval_id is not None
    await gate.approve(workflow.approval_id, reviewer="carol")

    history = get_case_history(case.case_id, audit)
    types = [event.event_type for event in history]
    assert types.index(AuditEventType.TOOL_CALL) < types.index(AuditEventType.DECISION)
    assert types.index(AuditEventType.DECISION) < types.index(
        AuditEventType.APPROVAL_PENDING
    )
    assert types.index(AuditEventType.APPROVAL_RESOLVED) < types.index(
        AuditEventType.ACTION_EXECUTED
    )
    note_payload = next(
        event.payload
        for event in history
        if event.event_type == AuditEventType.TOOL_CALL
        and "note_text" in event.payload.get("arguments_summary", {})
    )
    assert "text len=" in note_payload["arguments_summary"]["note_text"]
