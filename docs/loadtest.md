# Load and scale testing

This document records a real load test of the non-LLM compute paths in
clinical-ops-copilot, the one bottleneck it surfaced, the source fix, and the
measured before/after delta. Every number here comes from a k6 run executed
locally on the machine described below. Raw k6 output is committed under
`load/results/` as evidence.

## TL;DR

* A dedicated load harness (`load/harness_app.py`) exposes the repo's real
  parsers (X12 278, X12 835 + denial triage, HL7 v2), the synthetic FHIR
  patient store, and one agent-decision route wired to the deterministic
  `StubPlanner`. No live LLM call is made under load.
* The FHIR patient-fetch path re-ran full FHIR Pydantic validation on every
  request against an object that was already validated once at import.
* Replacing that per-request `model_validate(model_dump())` round-trip with
  `model_copy(deep=True)` raised sustained throughput on that endpoint by
  **10 to 15 percent** and cut p95 latency at fixed concurrency by
  **7 to 15 percent**, with all 332 existing tests still passing.

## Methodology

**Load generator:** k6 v2.1.0.

**Service under test:** `load/harness_app.py`, a single-worker uvicorn process
(`--workers 1`) bound to `127.0.0.1:8081`. Port 8081 is used because 8080 is
occupied by a LocalFHIR container on the development machine. A single worker is
deliberate: it makes the CPU-bound cost of each request path visible instead of
hiding it behind process-level parallelism.

**Endpoints exercised:**

| Endpoint | Method | Real code path exercised |
|---|---|---|
| `/parse/x12/278` | POST | `edi.parser.parse_278_request` (X12 278 prior-auth request) |
| `/parse/x12/835` | POST | `edi.x12_835.parse_835` + `edi.denial_triage.triage_remittance` |
| `/parse/hl7v2` | POST | `hl7v2.parser.parse_message` (ADT / ORU subset) |
| `/fhir/patient/{id}` | GET | `servers.clinical_data.patients.get_patient_record` |
| `/agent/decide` | POST | `agent.llm.StubPlanner.plan_decision` (offline, no network) |

**LLM safety under load:** the agent route is served only by `StubPlanner`, the
repo's own deterministic offline planner. The harness never constructs
`AnthropicPlanner` and never reads `ANTHROPIC_API_KEY`, so no live model call can
occur regardless of load. The stub route is a legitimate deliverable in its own
right: it lets the async request path and JSON serialization be measured without
paying for or depending on a model API.

**Scenarios:**

1. **Baseline** (`load/k6/baseline.js`): constant 10 VUs for 30s across the full
   endpoint mix. Steady-state behavior, not saturation.
2. **Ramp** (`load/k6/ramp.js`): `ramping-vus` from 0 to 120 VUs across the mix,
   to locate the saturation knee qualitatively.
3. **FHIR sweep** (`load/k6/fhir_sweep.js`): the isolated before/after
   instrument. Constant-VU runs at 5, 10, 20, 40, 80, 120 VUs against only
   `/fhir/patient/{id}`. For the headline delta, each of VUs 10 / 40 / 80 was
   run three times at 20s and the median taken, to damp laptop run-to-run noise.

**Reproduction:**

```bash
# one-shot: start harness on 8081, run sweep + baseline + ramp, save evidence
load/run_load.sh before      # profile current source
# (apply the fix, then)
load/run_load.sh after       # profile after the fix
```

The harness can also be run standalone:

```bash
.venv/bin/python -m uvicorn load.harness_app:app \
  --host 127.0.0.1 --port 8081 --workers 1
```

## Hardware note (honest qualifier)

All runs were on a local laptop, not isolated benchmarking hardware:

* Apple M3 Max, 14 cores, 36 GB RAM, macOS 26.5.2
* Python 3.11.15, uvicorn 0.49.0, pydantic 2.13.4, fhir.resources 8.2.0
* k6 and the service under test shared the same machine, so k6's own CPU cost
  and background OS activity are inside the measurement.

These are **relative** numbers: the before/after comparison is run back-to-back
on the same idle-ish machine, so the delta is meaningful, but the absolute req/s
ceilings would differ on server hardware or with multiple workers. Treat the
percentages, not the raw throughput, as the portable result.

## Saturation profile (before fix)

FHIR sweep, single 15s run per level (`load/results/before/`):

| VUs | throughput (req/s) | p95 (ms) | p99 (ms) | error rate |
|----:|-------------------:|---------:|---------:|-----------:|
| 5   | 3626 | 1.68 | 1.87 | 0% |
| 10  | 3674 | 3.15 | 3.57 | 0% |
| 20  | 3752 | 5.99 | 7.42 | 0% |
| 40  | 3754 | 11.55 | 14.66 | 0% |
| 80  | 3702 | 22.92 | 29.31 | 0% |
| 120 | 3661 | 37.03 | 54.89 | 0% |

Throughput plateaus at roughly 3700 req/s from 20 VUs onward while latency grows
linearly with concurrency. That is the classic signature of a single-worker,
CPU-bound service at saturation: adding VUs past the knee only lengthens the
queue, it does not add work done per second. The ceiling is set by per-request
CPU cost, which is exactly what the bottleneck fix targets.

## The bottleneck

**Where:** `servers/clinical_data/patients.py`, `get_patient_record`.

**Root cause, in three sentences.** The synthetic patient records are validated
once, at import, into `fhir.resources` Pydantic models, but `get_patient_record`
then re-validated on every single call by dumping the model to JSON and running
`Patient.model_validate` again. FHIR resource validation is deep and expensive
(nested constrained models), so this redundant round-trip cost about 30
microseconds per request out of a roughly 270-microsecond request budget, and it
bought no correctness because the source object was already valid. Replacing the
round-trip with `model_copy(deep=True)` keeps the caller-isolation guarantee (a
caller still cannot mutate the shared record) while skipping the re-validation
entirely.

Function-level microbenchmark (2000 iterations, same machine):

| operation | per call |
|---|---:|
| `model_validate(model_dump())` round-trip (before) | 56.6 us |
| `model_copy(deep=True)` (after) | 27.1 us |
| speedup | 2.1x |

The end-to-end HTTP delta is smaller than 2.1x because the endpoint still pays
for response serialization and ASGI/uvicorn overhead on every request; the fix
removes about 30 us from a roughly 270 us total, which predicts an
order-of-ten-percent throughput gain. The measured gain matches that prediction,
which is the honest ceiling for this change.

**The fix:**

```python
# before
return Patient.model_validate(patient.model_dump(mode="json"))
# after
return PATIENT_RECORDS[patient_id].model_copy(deep=True)
```

## Before / after (median of 3 trials, 20s each)

FHIR sweep, isolated endpoint (`load/results/compare_before/`,
`load/results/compare_after/`):

| VUs | req/s before | req/s after | throughput | p95 before (ms) | p95 after (ms) | p95 | p99 before (ms) | p99 after (ms) |
|----:|-------------:|------------:|-----------:|----------------:|---------------:|----:|----------------:|---------------:|
| 10  | 3606 | 4063 | +12.7% | 3.37 | 2.96 | -12.1% | 4.01 | 3.56 |
| 40  | 3745 | 4114 | +9.8%  | 11.62 | 10.75 | -7.5% | 13.37 | 13.46 |
| 80  | 3640 | 4204 | +15.5% | 23.65 | 20.09 | -15.1% | 27.64 | 23.03 |

Error rate was 0% in every cell, before and after. The p99 at 40 VUs is within
run-to-run noise (essentially flat); the throughput and p95 improvements are
consistent across all three concurrency levels.

## Mixed-workload context

The five-endpoint baseline and ramp show the same direction but a diluted
magnitude, because the FHIR fetch is only one of five requests per iteration
(`load/results/*/baseline.json`, `ramp.json`):

| scenario | req/s before | req/s after | p95 before (ms) | p95 after (ms) |
|---|---:|---:|---:|---:|
| baseline (10 VUs, 30s) | 5095 | 4945 | 2.57 | 2.78 |
| ramp (0 to 120 VUs) | 4715 | 5059 | 22.89 | 20.84 |

The baseline row is within noise (the fix touches one endpoint in five at low
concurrency); the ramp row, which spends more time near saturation, shows the
throughput and p95 improvement. The isolated FHIR sweep above is the clean
measurement; the mixed rows are context for how the change shows up in a blended
workload.

## Limitations (honest)

* **Local laptop, shared with the load generator.** Absolute req/s is not a
  server-grade number; only the before/after delta is portable.
* **Stubbed LLM.** The `/agent/decide` route measures the async request path and
  serialization, not real model latency. Production agent latency is dominated by
  the model call and is out of scope here by design.
* **Synthetic data only.** All fixtures are self-authored (see `edi/README.md`,
  `hl7v2/`), no PHI, no real payer traffic.
* **Single worker.** Multi-worker or multi-process deployment would raise the
  absolute ceiling and change the saturation shape; the per-request CPU win from
  the fix would still apply per worker.
* **One bottleneck, deliberately.** This exercise fixed the single clearest
  hot-path cost. The parsers were already efficient pure-string paths and were
  not the constraint.

## Evidence files

* `load/results/before/`: full sweep (6 VU levels) plus baseline and ramp,
  current source, raw k6 summary JSON and text.
* `load/results/after/`: same scenarios after the fix.
* `load/results/compare_before/`, `load/results/compare_after/`: the 3-trial
  median comparison at 10 / 40 / 80 VUs used for the headline table.
* `load/harness_app.py`, `load/k6/`, `load/run_load.sh`: the harness, scripts,
  and driver.
