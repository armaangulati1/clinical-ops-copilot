"""PHI-safe logging for FHIR-backed prior-auth runs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.approval_store import InMemoryApprovalStore
from agent.audit import InMemoryAuditTrail, get_case_history
from agent.config import AgentConfig
from agent.executor import ActionExecutor
from agent.gate import ApprovalGate
from agent.llm import StubPlanner
from agent.mcp_host import MockMcpHost, summarize_result
from agent.run_log import RunLogWriter
from agent.workflow import run_case_with_gate
from schemas.approval import AuditEventType
from schemas.cases import Case
from schemas.phi_redaction import (
    TOKEN_FREE_TEXT,
    TOKEN_MRN,
    find_raw_phi_literals,
)
from schemas.seed_data import POLICIES
from tests.test_fhir_redaction import seed_patient_resource

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = PROJECT_ROOT / "tests/fixtures/fhir_patient_78748.json"

PHI_LITERALS = (
    "Evelyn Carter",
    "MRN-8827441",
    "1975-03-14",
    "(415) 555-0192",
    "742 Evergreen Terrace",
)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _fhir_phi_case() -> Case:
    policy = POLICIES["t2d"]
    return Case(
        case_id="case-092",
        clinical_note=(
            "Structured FHIR chart available for this Ozempic prior-auth request. "
            "Note intentionally omits numeric criteria; rely on EHR structured data."
        ),
        payer_policy=policy,
        drug=policy.drug,
        condition=policy.condition,
        patient_id="phi-seed-1",
    )


@pytest.mark.anyio
async def test_fhir_mode_emits_no_raw_patient_identifiers(tmp_path: Path) -> None:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    note_payload = {
        "extraction": {
            "a1c_percent": None,
            "metformin_trial_months": None,
            "bmi": None,
            "diabetes_duration_years": None,
        },
        "field_confidence": {},
        "needs_review": [],
        "evidence": {},
        "field_provenance": {},
        "review_threshold": 0.75,
    }
    leaky_observation = dict(fixture["observations"]["http://loinc.org|4548-4"][0])
    leaky_observation["note"] = [
        {
            "text": (
                "Evelyn Carter MRN-8827441 DOB 1975-03-14 "
                "phone (415) 555-0192 address 742 Evergreen Terrace"
            )
        }
    ]
    observations = dict(fixture["observations"])
    observations["http://loinc.org|4548-4"] = [leaky_observation]
    config = AgentConfig(
        project_root=tmp_path,
        runs_dir=tmp_path / "runs",
    )
    host = MockMcpHost(
        extraction_payload=note_payload,
        policy_payload=POLICIES["t2d"].model_dump(mode="json"),
        fhir_observations=observations,
        fhir_conditions=fixture["conditions"],
        fhir_medications=fixture["medications"],
        fhir_patient_record=seed_patient_resource(),
    )
    audit = InMemoryAuditTrail()
    store = InMemoryApprovalStore()
    gate = ApprovalGate(store, audit, ActionExecutor(host, audit))
    writer = RunLogWriter(config.runs_dir)

    workflow = await run_case_with_gate(
        _fhir_phi_case(),
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
    assert leaks == [], f"raw PHI leaked into logs/audit: {leaks}"
    assert TOKEN_FREE_TEXT in combined
    assert TOKEN_MRN in combined

    assert workflow.approval_id is not None
    pending = store.get(workflow.approval_id)
    assert pending is not None
    provenance = pending.extraction.field_provenance
    assert provenance["a1c_percent"].startswith("FHIR Observation 4548-4")

    history = get_case_history("case-092", audit)
    provenance_events = [
        event
        for event in history
        if event.event_type == AuditEventType.FIELD_PROVENANCE
    ]
    assert provenance_events
    assert (
        provenance_events[0]
        .payload["field_provenance"]["a1c_percent"]
        .startswith("FHIR Observation 4548-4")
    )


def test_tool_result_summary_redacts_structured_patient_resource() -> None:
    """Would fail if FHIR Patient PHI were written raw to run/audit sinks."""
    summary = summarize_result(seed_patient_resource())
    combined = json.dumps(summary)
    leaks = find_raw_phi_literals(combined, PHI_LITERALS)
    assert leaks == [], f"structured Patient PHI leaked in tool summary: {leaks}"
