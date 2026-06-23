"""UI smoke tests with FastAPI TestClient."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agent.approval_store import InMemoryApprovalStore
from agent.audit import InMemoryAuditTrail
from agent.executor import ActionExecutor
from agent.gate import ApprovalGate
from agent.llm import StubPlanner
from agent.mcp_host import MockMcpHost
from agent.workflow import run_case_with_gate
from schemas.loader import load_case_file
from servers.clinical_data.extractor import extract
from ui.app import create_app
from ui.deps import AppServices, build_services

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_ui_queue_approve_and_reject_smoke() -> None:
    case = load_case_file(PROJECT_ROOT / "data/cases/case-001.json")
    extraction = extract(case.clinical_note)
    host = MockMcpHost(
        extraction_payload=extraction.model_dump(mode="json"),
        policy_payload=case.payer_policy.model_dump(mode="json"),
    )
    audit = InMemoryAuditTrail()
    store = InMemoryApprovalStore()
    gate = ApprovalGate(store, audit, ActionExecutor(host, audit))
    services = AppServices(
        config=build_services(PROJECT_ROOT).config,
        store=store,
        audit=audit,
        gate=gate,
        host=host,
    )
    app = create_app(services)

    workflow = await run_case_with_gate(case, host, StubPlanner(), gate)
    assert workflow.approval_id is not None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        queue = await client.get("/")
        assert queue.status_code == 200
        assert case.case_id in queue.text

        detail = await client.get(f"/approvals/{workflow.approval_id}")
        assert detail.status_code == 200
        assert "create_task" in detail.text

        approve = await client.post(f"/approvals/{workflow.approval_id}/approve")
        assert approve.status_code == 303
        assert host.clinic_ops_counters.get("create_task", 0) == 1

    case_two = load_case_file(PROJECT_ROOT / "data/cases/case-002.json")
    extraction_two = extract(case_two.clinical_note)
    host_two = MockMcpHost(
        extraction_payload=extraction_two.model_dump(mode="json"),
        policy_payload=case_two.payer_policy.model_dump(mode="json"),
    )
    gate_two = ApprovalGate(store, audit, ActionExecutor(host_two, audit))
    services_two = AppServices(
        config=services.config,
        store=store,
        audit=audit,
        gate=gate_two,
        host=host_two,
    )
    app_two = create_app(services_two)
    workflow_two = await run_case_with_gate(
        case_two,
        host_two,
        StubPlanner(),
        gate_two,
    )
    assert workflow_two.approval_id is not None

    transport_two = ASGITransport(app=app_two)
    async with AsyncClient(transport=transport_two, base_url="http://test") as client:
        reject = await client.post(f"/approvals/{workflow_two.approval_id}/reject")
        assert reject.status_code == 303
        assert host_two.clinic_ops_counters.get("create_task", 0) == 0
