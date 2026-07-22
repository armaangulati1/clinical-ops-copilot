"""Load-test harness ASGI app for clinical-ops-copilot.

This is a thin, honestly-labeled HTTP surface that mounts the repo's REAL,
non-LLM compute paths (X12 278 / 835 parsers, HL7 v2 parser, the synthetic FHIR
patient store) plus one agent-decision route wired to the deterministic
``StubPlanner``. Its sole purpose is to make those code paths reachable by an
external load generator (k6) without touching production wiring.

Why a dedicated app rather than the MCP StreamableHTTP server:

* The clinical-data MCP server speaks JSON-RPC over SSE, which a plain HTTP load
  generator cannot exercise as simple request/response.
* The agent-decision loop normally calls a live LLM. Under load that is both
  expensive and non-deterministic. Here it is served exclusively by
  ``StubPlanner`` (the repo's own offline planner). This module imports only
  ``StubPlanner`` and never constructs ``AnthropicPlanner`` or reads
  ``ANTHROPIC_API_KEY``, so no network LLM call can occur regardless of load.

Run:

    uvicorn load.harness_app:app --host 127.0.0.1 --port 8081 --workers 1

Port 8081 is used deliberately: 8080 is occupied by a LocalFHIR container on the
development machine.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from agent.llm import StubPlanner
from edi.denial_triage import triage_remittance
from edi.errors import X12ParseError
from edi.parser import parse_278_request
from edi.x12_835 import parse_835
from hl7v2.errors import HL7ParseError
from hl7v2.parser import parse_message
from schemas.loader import load_case_file
from servers.clinical_data.extractor import extract
from servers.clinical_data.patients import get_patient_record, list_patient_ids

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Hard guarantee: this harness never issues a live LLM call. The agent route is
# served only by StubPlanner (imported above); AnthropicPlanner is never built.
_STUB_PLANNER = StubPlanner()


@lru_cache(maxsize=1)
def _decision_inputs() -> tuple[Any, Any, Any]:
    """Load a single case once and derive stub-planner inputs.

    Cached so the per-request agent route measures the stub planner plus
    extraction reuse, not repeated disk reads of the same fixture.
    """
    case = load_case_file(PROJECT_ROOT / "data/cases/case-001.json")
    extraction = extract(case.clinical_note, policy=case.payer_policy)
    return case, extraction, case.payer_policy


def create_app() -> FastAPI:
    app = FastAPI(title="clinical-ops-copilot load harness", version="0.1.0")

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "stub_llm": True})

    @app.post("/parse/x12/278")
    async def parse_x12_278(request: Request) -> JSONResponse:
        body = (await request.body()).decode("utf-8")
        try:
            parsed = parse_278_request(body)
        except X12ParseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse(
            {
                "transaction_control": parsed.transaction_control,
                "submitter_reference": parsed.submitter_reference,
                "drug": parsed.drug,
                "condition": parsed.condition,
                "note_chars": len(parsed.clinical_note),
            }
        )

    @app.post("/parse/x12/835")
    async def parse_x12_835(request: Request) -> JSONResponse:
        body = (await request.body()).decode("utf-8")
        try:
            remittance = parse_835(body)
            triage = triage_remittance(remittance)
        except X12ParseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse(
            {
                "trace_number": remittance.trace_number,
                "claim_count": len(remittance.claims),
                "recommendations": [t.recommendation.value for t in triage],
            }
        )

    @app.post("/parse/hl7v2")
    async def parse_hl7(request: Request) -> JSONResponse:
        body = (await request.body()).decode("utf-8")
        try:
            message = parse_message(body)
        except HL7ParseError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse(
            {
                "message_type": message.message_type,
                "patient_family": (
                    message.patient.family_name if message.patient else None
                ),
                "observation_count": len(message.observations),
            }
        )

    @app.get("/fhir/patient/{patient_id}")
    async def fhir_patient(patient_id: str) -> JSONResponse:
        try:
            patient = get_patient_record(patient_id)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        return JSONResponse(patient.model_dump(mode="json"))

    @app.get("/fhir/patient-ids")
    async def fhir_patient_ids() -> JSONResponse:
        return JSONResponse({"patient_ids": list_patient_ids()})

    @app.post("/agent/decide")
    async def agent_decide() -> JSONResponse:
        case, extraction, policy = _decision_inputs()
        decision = await _STUB_PLANNER.plan_decision(case, extraction, policy, [])
        return JSONResponse(
            {
                "action": decision.action.value,
                "confidence": decision.confidence,
                "missing_fields": decision.missing_fields,
                "stub": True,
            }
        )

    @app.get("/", response_class=PlainTextResponse)
    async def index() -> str:
        return "clinical-ops-copilot load harness (stub LLM). See /health."

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("LOAD_HARNESS_PORT", "8081"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
