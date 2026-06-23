"""PHI redaction unit and pipeline scan tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.approval_store import InMemoryApprovalStore
from agent.audit import InMemoryAuditTrail
from agent.config import AgentConfig
from agent.executor import ActionExecutor
from agent.gate import ApprovalGate
from agent.llm import StubPlanner
from agent.mcp_host import MockMcpHost
from agent.run_log import RunLogWriter
from agent.workflow import run_case_with_gate
from schemas.cases import Case
from schemas.phi_redaction import (
    TOKEN_ADDRESS,
    TOKEN_DOB,
    TOKEN_EMAIL,
    TOKEN_MRN,
    TOKEN_NAME,
    TOKEN_PHONE,
    TOKEN_SSN,
    find_raw_phi_literals,
    redact_payload,
    redact_text,
)
from schemas.policies import PayerPolicy
from servers.clinical_data.extractor import extract

PROJECT_ROOT = Path(__file__).resolve().parents[1]

PHI_LITERALS = (
    "Evelyn Carter",
    "MRN-8827441",
    "03/14/1975",
    "evelyn.carter@example.com",
    "(415) 555-0192",
    "123-45-6789",
    "742 Evergreen Terrace",
)


def _phi_case() -> Case:
    note = (
        "Prior-auth request. Patient: Evelyn Carter, MRN: MRN-8827441, "
        "DOB: 03/14/1975. Email: evelyn.carter@example.com. "
        "Phone: (415) 555-0192. SSN: 123-45-6789. "
        "Address: 742 Evergreen Terrace. DAS28 score: 4.8. Failed DMARDs: 2."
    )
    policy = PayerPolicy(
        drug="Humira",
        condition="rheumatoid arthritis",
        required_criteria_fields=["das28_score", "failed_dmards"],
        rules="Coverage requires documented DAS28 and failed DMARD trials.",
    )
    return Case(
        case_id="case-099",
        clinical_note=note,
        payer_policy=policy,
        drug="Humira",
        condition="rheumatoid arthritis",
    )


def test_redact_text_masks_identifiers_but_keeps_clinical_facts() -> None:
    raw = (
        "Patient: Evelyn Carter, MRN: MRN-8827441, email evelyn.carter@example.com. "
        "DAS28 score: 4.8"
    )
    redacted = redact_text(raw)
    assert "Evelyn Carter" not in redacted
    assert TOKEN_NAME in redacted
    assert TOKEN_MRN in redacted
    assert TOKEN_EMAIL in redacted
    assert "4.8" in redacted


def test_redact_payload_masks_identifier_fields() -> None:
    payload = {
        "patient_name": "Evelyn Carter",
        "das28_score": 4.8,
        "to": "evelyn.carter@example.com",
    }
    redacted = redact_payload(payload)
    assert redacted["patient_name"] == TOKEN_NAME
    assert redacted["das28_score"] == 4.8
    assert redacted["to"] == TOKEN_EMAIL


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_full_pipeline_emits_no_raw_phi(tmp_path: Path) -> None:
    case = _phi_case()
    extraction = extract(case.clinical_note)
    config = AgentConfig(
        project_root=tmp_path,
        runs_dir=tmp_path / "runs",
    )
    host = MockMcpHost(
        extraction_payload=extraction.model_dump(mode="json"),
        policy_payload=case.payer_policy.model_dump(mode="json"),
        config=config,
    )
    audit = InMemoryAuditTrail()
    store = InMemoryApprovalStore()
    gate = ApprovalGate(store, audit, ActionExecutor(host, audit))
    writer = RunLogWriter(config.runs_dir)

    await run_case_with_gate(
        case,
        host,
        StubPlanner(),
        gate,
        config=config,
        writer=writer,
    )

    emitted: list[str] = []
    if writer.path.exists():
        emitted.append(writer.path.read_text(encoding="utf-8"))
    for event in audit._events:
        emitted.append(json.dumps(event.model_dump(mode="json")))

    combined = "\n".join(emitted)
    leaks = find_raw_phi_literals(combined, PHI_LITERALS)
    assert leaks == [], f"raw PHI leaked: {leaks}"
    redaction_tokens = (
        TOKEN_NAME,
        TOKEN_MRN,
        TOKEN_EMAIL,
        TOKEN_PHONE,
        TOKEN_DOB,
        TOKEN_SSN,
        TOKEN_ADDRESS,
    )
    assert any(token in combined for token in redaction_tokens), (
        "expected at least one PHI redaction token in emitted logs"
    )
