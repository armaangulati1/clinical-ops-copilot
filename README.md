# clinical-ops-copilot

MCP-powered prior-auth triage agent: extract chart fields, check payer policy, decide submit / request-more-info / deny-risk, and route clinic-ops actions through a human approval gate.

**[Live API health](https://clinical-data-mcp.fly.dev/health)** · **[Tests](#tests)** · **[MIT License](LICENSE)** · **[Demo (2 min)](https://www.loom.com/share/TBD)** *(Loom placeholder)*

---

## Results

*Source: `evals/results/locked_test.json` (n=16, locked split), `evals/results/tuning_comparison.md`, `tests/test_clinic_ops_reliability.py`. Model: `claude-sonnet-4-5`.*

| Metric | Value |
|--------|------:|
| **Macro-F1 (locked test, n=16)** | **0.9373** |
| Pre-fix full-48 baseline macro-F1 | 0.844 |
| Accuracy (locked test) | 0.9375 |
| **deny-risk recall** | **1.000** (was **0.600** pre-fix) |
| submit F1 / recall | 0.9231 / 1.000 |
| request-more-info F1 / recall | 0.8889 / 0.800 |
| deny-risk F1 / precision | 1.000 / 1.000 |
| Trajectory correctness | 68.75% *(strict rubric; action-mapping variants often warn)* |
| Latency p50 / p95 | 10,498.08 ms / 13,328.36 ms |
| Avg cost / case | $0.017478 |
| **Reliability (clinic-ops chaos tests)** | Completes under **30%** injected failure rate; **40/40** idempotent `send_email` ops → **40** backend sends (no doubles); **20/20** action bundles complete once per key |

**Caveats:** Synthetic cases with human-confirmed labels; locked test n=16 (wide CIs). Email LLM judge validated on 8 human ratings (0% exact agreement, MAE 1.38, Pearson r ≈ −0.29) and **excluded from scoring**. Remaining decision errors stay **overconfident** (~0.95 on failures, e.g. locked `case-039`).

---

## FHIR integration (Phases 0–6)

An agentic prior-auth system that reads **live EHR data via FHIR** (HAPI + Synthea), fuses structured FHIR facts with free-text note extraction (with per-field provenance), routes actions through a **human approval gate**, and is measured by a dedicated FHIR eval harness.

*Source: `evals/results/fhir.json`, `evals/results/fhir_guardrail_comparison.md` (n=12 Ozempic/T2D cases, `claude-sonnet-4-5`).*

### Results (deltas first)

| What changed | Before | After |
|--------------|--------|-------|
| **FHIR fusion vs note-only** (macro-F1) | **0.2456** note-only | **1.0000** FHIR path |
| **Missing-field guardrail** (request-more-info recall, FHIR path) | **0.286** (2/7) planner only | **1.000** (7/7) planner + guardrail |
| **deny-risk recall** (FHIR path, both runs) | **1.000** (4/4) | **1.000** (4/4) — legitimate denials preserved |

**CAVEATS:** Small **n ≈ 12**; **synthetic Synthea** patients on local HAPI; a **decision-logic eval** (labels = payer policy applied to the same FHIR facts the agent reads, not independent chart review); **one guardrail iteration** informed by the held-out aggregate. Do not read the post-guardrail run as production accuracy.

### Architecture

```
┌──────────────────┐     stdio MCP      ┌─────────────────────┐
│ Agent            │───────────────────►│ clinical-data MCP   │
│ planner +        │                    │ CLINICAL_DATA_      │
│ guardrails +     │     stdio MCP      │ SOURCE=fhir         │
│ approval gate    │───────────────────►│ clinic-ops (actions)│
└──────────────────┘                    └──────────┬──────────┘
                                                   │ FHIR REST
                                                   ▼
                                        ┌─────────────────────┐
                                        │ FhirClient          │
                                        │ → HAPI FHIR         │
                                        │ ← Synthea bundles   │
                                        └─────────────────────┘
```

Fusion and provenance live in `agent/fhir_facts.py`; FHIR-down fallback and PHI-safe logging in `agent/fhir_resilience.py` and `schemas/fhir_redaction.py`.

### How to run (local FHIR path)

```bash
make fhir-up                    # HAPI on :8080
make load-synthea               # once: load ~119 Synthea patients

export CLINICAL_DATA_SOURCE=fhir
export FHIR_BASE_URL=http://localhost:8080/fhir
export ANTHROPIC_API_KEY="<your key>"   # never commit .env

uv run evals --fhir             # always local stdio MCP + HAPI (ignores CLINICAL_DATA_URL)
```

Single-case demo with provenance: see [docs/fhir_demo_script.md](docs/fhir_demo_script.md).

**Docs:** [docs/fhir_teardown.md](docs/fhir_teardown.md) · [evals/fhir/LABEL_REVIEW.md](evals/fhir/LABEL_REVIEW.md)

---

## Architecture

```
┌─────────────┐     ┌──────────────────────────────────────┐
│  Approval   │     │  Agent (planner + guardrails + logs) │
│  UI :8080   │────►│  MCP client                          │
└─────────────┘     └───┬──────────────────────┬───────────┘
                        │ StreamableHTTP+auth  │ stdio
                        ▼                      ▼
              ┌─────────────────┐    ┌─────────────────┐
              │ clinical-data   │    │ clinic-ops      │
              │ (Fly, Server A) │    │ (local, actions)│
              │ extract, policy │    │ email, tasks, … │
              └─────────────────┘    └─────────────────┘
```

**Safety model:** human approval gate before state-changing clinic-ops tools · deterministic missing-field guardrail (routes submit **or deny-risk** to request-more-info when required fields are null/`needs_review`; legitimate denials with all fields present pass through) · PHI redaction on logs/audit · prompt-injection guard on tool args · chart path sandbox (`data/charts` only on server).

---

## How to run

### Prerequisites

```bash
uv sync --dev
cp .env.example .env   # add ANTHROPIC_API_KEY; never commit .env
```

### Agent (local clinic-ops + deployed clinical-data)

```bash
export CLINICAL_DATA_URL="https://clinical-data-mcp.fly.dev/mcp"
export CLINICAL_DATA_AUTH_TOKEN="<your fly secret>"
export EXTRACTOR_BACKEND=stub
export ANTHROPIC_API_KEY="<your key>"

uv run python -m agent --case case-001
```

Omit `CLINICAL_DATA_URL` to launch clinical-data over stdio locally instead.

### Approval UI

```bash
uv run python -m ui
# → http://127.0.0.1:8080
```

### Evals (locked test split)

```bash
uv run evals --split evals/splits/locked_test.json
```

### Deploy clinical-data (Fly)

See [docs/deploy_fly.md](docs/deploy_fly.md). Redeploy: `fly deploy --ha=false` (stateful MCP requires one machine).

---

## Tests

```bash
uv run ruff check . && uv run mypy .
uv run pytest -m "not network" -q    # 137 tests, CI-safe
```

Post-deploy smoke (optional): `CLINICAL_DATA_DEPLOY_URL=https://clinical-data-mcp.fly.dev uv run pytest -m deploy -q`

---

## Repo map

| Path | Role |
|------|------|
| `agent/` | Orchestrator, planner, guardrails, MCP host |
| `servers/clinical_data/` | Read-side MCP (deployed on Fly) |
| `servers/clinic_ops/` | Action-side MCP (stdio) |
| `ui/` | Human approval gate (FastAPI + HTMX) |
| `evals/` | Metrics, splits, regression gate, FHIR eval (`evals/fhir/`) |
| `fhir_client/` | Typed FHIR REST client |
| `docs/teardown.md` | Written post-mortem (employer-facing) |
| `docs/fhir_teardown.md` | FHIR integration post-mortem |
| `docs/demo_script.md` | 2-minute Loom shot list |
| `docs/fhir_demo_script.md` | 60-second FHIR + provenance demo |

---

## Docs

- [docs/teardown.md](docs/teardown.md) — problem, approach, results, failures
- [docs/fhir_teardown.md](docs/fhir_teardown.md) — FHIR integration: fusion, guardrail, honest deltas
- [docs/demo_script.md](docs/demo_script.md) — demo recording script
- [docs/fhir_demo_script.md](docs/fhir_demo_script.md) — 60s FHIR + provenance shot list
- [docs/safety.md](docs/safety.md) — PHI, injection, approval policy
- [docs/transport_tradeoff.md](docs/transport_tradeoff.md) — why stateful StreamableHTTP
- [evals/results/tuning_comparison.md](evals/results/tuning_comparison.md) — before/after tuning table
