# 60-second FHIR demo shot list

**Goal:** Show a real Synthea patient’s structured labs/diagnosis/meds pulled over FHIR, fused into a prior-auth decision, with per-field provenance in the audit trail.  
**Total:** ~60 seconds. Terminal only (or terminal + small browser tab for HAPI metadata).

**Prereqs:** `make fhir-up`, `make load-synthea` (once), `ANTHROPIC_API_KEY` in `.env`. Do **not** set `CLINICAL_DATA_URL` — local stdio MCP only.

---

## 0:00–0:08 — Live FHIR is up

**Screen:** Terminal

**Say:**  
“Prior-auth needs structured EHR facts, not just the note. Local HAPI is serving Synthea patients over FHIR.”

**Do:**

```bash
curl -s http://localhost:8080/fhir/metadata | python -c "import sys,json; m=json.load(sys.stdin); print(m['software']['name'], m['fhirVersion'])"
```

**Show:** `HAPI FHIR Server` (or similar) + FHIR version line.

---

## 0:08–0:35 — Agent run: sparse note + FHIR fusion

**Screen:** Terminal, repo root

**Say:**  
“Case 057: the note deliberately omits A1C and BMI. The agent passes `patient_id` 78748; clinical-data reads FHIR and fuses with the note.”

**Do:**

```bash
export CLINICAL_DATA_SOURCE=fhir
export FHIR_BASE_URL=http://localhost:8080/fhir
export EXTRACTOR_BACKEND=stub

uv run python - <<'PY'
import asyncio
from pathlib import Path
from agent.approval_store import InMemoryApprovalStore
from agent.audit import JsonlAuditTrail, get_case_history
from agent.config import load_config
from agent.executor import ActionExecutor
from agent.gate import ApprovalGate
from agent.llm import AnthropicPlanner
from agent.mcp_host import StdioMcpHost
from agent.workflow import run_case_with_gate
from schemas.approval import AuditEventType
from schemas.loader import load_case_file

ROOT = Path(".")
case = load_case_file(ROOT / "evals/fhir/cases/case-057.json")
config = load_config(ROOT)
audit = JsonlAuditTrail(ROOT / "data/audit/demo_fhir.jsonl")
store = InMemoryApprovalStore()
host = asyncio.run(StdioMcpHost.connect(config))
planner = AnthropicPlanner(config.anthropic_model)
gate = ApprovalGate(store, audit, ActionExecutor(host, audit))

async def main():
    try:
        result = await run_case_with_gate(case, host, planner, gate, config=config)
        print(f"{case.case_id}: {result.decision.action.value} (confidence={result.decision.confidence:.2f})")
        pending = store.get(result.approval_id) if result.approval_id else None
        if pending:
            ex = pending.extraction.extraction
            print(f"A1C={ex.a1c_percent}  BMI={ex.bmi}  metformin_mo={ex.metformin_trial_months}")
            for field, source in sorted(pending.extraction.field_provenance.items()):
                print(f"  {field}: {source}")
    finally:
        await host.close()

asyncio.run(main())
PY
```

**Show:** Decision line (expect `deny-risk` — A1C 6.72% &lt; 7.0% threshold). Printed A1C/BMI/metformin from FHIR. Provenance lines with `FHIR Observation` / `FHIR Condition` sources.

**Say:**  
“Numbers came from FHIR, not the note. A1C below 7.0% → deny-risk with all required fields present — guardrail does not override.”

---

## 0:35–0:52 — Audit trail: provenance event

**Screen:** Same terminal

**Say:**  
“Audit JSONL records field provenance for reviewers — PHI-redacted.”

**Do:**

```bash
uv run python - <<'PY'
import json
from pathlib import Path
from agent.audit import JsonlAuditTrail, get_case_history
from schemas.approval import AuditEventType

audit = JsonlAuditTrail(Path("data/audit/demo_fhir.jsonl"))
for event in get_case_history("case-057", audit):
    if event.event_type == AuditEventType.FIELD_PROVENANCE:
        print(json.dumps(event.payload, indent=2))
        break
PY
```

**Show:** `field_provenance` block with `a1c_percent` → `FHIR Observation 4548-4 …` (and other fields).

---

## 0:52–1:00 — Measured delta (one line)

**Screen:** `evals/results/fhir_guardrail_comparison.md` or README FHIR table

**Say:**  
“On a 12-case FHIR eval: macro-F1 went from 0.25 note-only to 1.0 with fusion; guardrail fixed over-denial on missing fields — request-more-info recall 0.29 to 1.0 — with caveats: synthetic data, small n, decision-logic labels.”

**Do:** Scroll the deltas table. Do **not** say “100% accurate in production.”

---

## Recording notes

- Redact `ANTHROPIC_API_KEY`; never paste tokens on screen.
- `data/audit/demo_fhir.jsonl` is synthetic Synthea — safe to show; delete after recording if desired.
- If HAPI is down: `make fhir-up` and retry; do not fall back to Fly `CLINICAL_DATA_URL` for this demo.
