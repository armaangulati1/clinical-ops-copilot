# FHIR integration: what I built and where it still falls short

## The problem

Prior auth does not run on prose alone. Payer rules ask for structured facts — A1C, diagnosis codes, medication trials, BMI — that often live in the EHR, not in the faxed cover sheet or the one-paragraph note a clinician pasted into the portal. If your agent only reads free text, you either hallucinate numbers or punt everything to “request more info.” That is expensive and it erodes trust.

I wanted to wire the prior-auth copilot to **real structured clinical data** without pretending I had Epic in my apartment. The bar: live FHIR reads, fuse them with note extraction, show **where each fact came from**, degrade gracefully when FHIR is down, and measure whether decision logic improves — honestly.

## Approach

**Local FHIR stack (Phases 0–2).** Dockerized HAPI FHIR on `:8080`, Synthea bundles loaded (~119 synthetic patients), typed `FhirClient` with LOINC-aware observation search and retries.

**FHIR-backed MCP server (Phase 3).** `clinical-data` can run in `CLINICAL_DATA_SOURCE=fhir` mode: given a `patient_id`, it pulls Observations, Conditions, and MedicationStatements over REST and maps them to payer-policy fields (Ozempic/T2D: A1C 4548-4, metformin trial, BMI, T2D condition).

**Fusion + provenance (Phase 4).** `agent/fhir_facts.py` merges note extraction with FHIR facts. Each field records provenance (`note` vs `FHIR Observation …` with LOINC and effective date). The audit trail emits a `field_provenance` event — reviewers can see what came from the chart vs the EHR.

**Reliability (Phase 5).** If HAPI is unreachable, the agent falls back to note-only extraction, logs a `fhir_fallback` audit event, and redacts Patient resources before anything hits logs.

**Guardrail fix (Phase 6).** The original missing-field guardrail only blocked `submit` when required fields were absent. On the FHIR eval, the planner often chose `deny-risk` instead of `request-more-info` when metformin duration or diabetes duration was missing — five cases on a 12-case set. I extended the deterministic post-planner guardrail: **any** submit or deny-risk with a missing required field routes to `request-more-info`, without touching legitimate denials where all fields are present but thresholds fail (e.g. A1C 6.72% &lt; 7.0%).

**Eval harness.** Twelve held-out Synthea patients, sparse notes by design, labels derived by applying the same Ozempic/T2D policy to the FHIR facts the agent reads. Labels live in `evals/fhir/`; the agent never sees them at runtime.

## Results (committed numbers, deltas first)

From `evals/results/fhir.json` and `evals/results/fhir_guardrail_comparison.md`:

| Delta | Before | After |
|-------|--------|-------|
| **FHIR fusion vs note-only** (macro-F1, n=12) | **0.2456** note-only | **1.0000** FHIR path |
| **Guardrail on FHIR path** (request-more-info recall) | **0.286** (2/7) planner only | **1.000** (7/7) planner + guardrail |
| **deny-risk recall** (FHIR path) | **1.000** (4/4) | **1.000** (4/4) |

Note-only baseline accuracy is **0.5833** — same headline accuracy as the pre-guardrail FHIR run — but macro-F1 stays **0.2456** because it never recovers submit or deny-risk without structured labs. FHIR fusion carries the signal sparse notes omit.

Latency on the FHIR eval: **p50 13,071 ms**, **p95 15,752 ms**, **~$0.019/case** (Claude Sonnet 4.5 + local MCP).

**CAVEATS I will say out loud:** n≈12, synthetic Synthea, decision-logic labels (policy on the same FHIR input), one guardrail iteration informed by the aggregate. The post-guardrail run is **not** a headline “100% accuracy in production.” It is a controlled before/after on a tiny set.

## What I would do differently

1. **Real EHR auth, not localhost HAPI.** SMART-on-FHIR / OAuth, patient context, and tenant isolation are the real integration work. HAPI + Synthea proved the pipeline; they did not prove hospital rollout.

2. **Larger, messier charts.** Synthea is clean. Real FHIR has duplicates, stale labs, missing codes, and broken MedicationStatement timing. I would eval on de-identified production exports or vendor sandboxes before claiming generalization.

3. **Separate guardrail design from eval iteration.** The deny-risk extension is general correctness logic, but I only measured it on this 12-case set. I would add unit cases per policy and resist tuning to the aggregate.

4. **HL7 v2 and X12 are still ahead.** FHIR covers structured clinical facts; ADT/ORU feeds and 278/275 transactions are how much of prior auth actually moves. This repo does not touch those yet.

5. **Confidence calibration.** Pre-guardrail FHIR errors were systematic over-denial, not random. I would still gate high-stakes denials on human review.

## Where it falls short

| Gap | Evidence |
|-----|----------|
| **Tiny eval** | n=12; one case flip moves metrics sharply |
| **Synthetic data** | Synthea patients; `synthea/` gitignored, not real PHI |
| **Decision-logic labels** | Not independent chart review; same facts as agent input |
| **No SMART-on-FHIR** | Local HAPI only; Fly deploy is note-extraction MCP, not live hospital EHR |
| **Planner cost/latency** | ~13s p50 per case with Claude + tool loop |
| **Note-only path unchanged** | Without `patient_id`, behavior is still the older baseline |

## Closing

Read structured EHR data through a bounded MCP server, fuse with notes, prove provenance in the audit trail, fail closed to notes when FHIR is down, and measure fusion + guardrail deltas with caveats visible. Portfolio-grade integration — not a claim that prior auth is solved on live Epic.
