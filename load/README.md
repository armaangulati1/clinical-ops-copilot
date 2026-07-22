# Load testing

A k6 load test of the non-LLM compute paths in clinical-ops-copilot, plus the
source fix it produced. Full write-up with methodology, before/after tables, and
the bottleneck root cause: [`docs/loadtest.md`](../docs/loadtest.md).

## What is here

| Path | Purpose |
|---|---|
| `harness_app.py` | A thin FastAPI app that exposes the repo's real parsers (X12 278, X12 835 + triage, HL7 v2), the synthetic FHIR patient store, and one agent route backed by the deterministic `StubPlanner`. No live LLM call is ever made. |
| `k6/baseline.js` | Constant-load mixed-endpoint scenario. |
| `k6/ramp.js` | Ramping-VUs scenario to find the saturation knee. |
| `k6/fhir_sweep.js` | Isolated single-endpoint sweep used for the before/after comparison. |
| `run_load.sh` | Driver: starts the harness on port 8081, runs the sweep + baseline + ramp, saves raw k6 output under `results/<label>/`. |
| `results/` | Committed raw k6 evidence (summary JSON + text). |

## Quick start

```bash
# requires k6 on PATH and the repo .venv
load/run_load.sh before
```

Port 8081 is used deliberately: 8080 is occupied by a LocalFHIR container on the
development machine. The harness runs single-worker on purpose, to make
per-request CPU cost visible rather than hiding it behind process parallelism.

## Safety notes

* **No live LLM.** `harness_app.py` imports only `StubPlanner` and never
  constructs `AnthropicPlanner` or reads `ANTHROPIC_API_KEY`.
* **Synthetic data only.** All request payloads are self-authored fixtures from
  `edi/fixtures/` and `hl7v2/fixtures/`. No PHI.
