# clinical-data MCP server

Read-side MCP server for patient records, payer policies, and chart extraction.

## Extraction tools (two separate paths)

| Tool | Schema | Backend | Purpose |
|------|--------|---------|---------|
| `extract_chart` | `ExtractionResult` | Prior-auth (`EXTRACTOR_BACKEND`) | Humira/Ozempic/Aimovig prior-auth fields + confidence |
| `extract_oncology_chart` | `oncology_schema.ExtractionOutput` | [ChartExtractor API](https://chartextract.onrender.com) | Oncology variables (8-field `OncologyExtract`) |

**ChartExtractor is oncology-only.** It does not produce prior-auth `Extraction` fields
(DAS28, A1C, migraine-days, etc.). Prior-auth extraction lives in
`priorauth_extractor/` — a separate agentic pipeline built in this repo, modeled on
ChartExtractor's router → extractors → validator → verifier pattern.

## Prior-auth extractor (`priorauth_extractor/`)

| Stage | Module | Role |
|-------|--------|------|
| Router | `router.py` | Pick RA / T2D / migraine path from `PayerPolicy` |
| Extractors | `extractors.py` | Claude structured output → `Extraction` candidates |
| Validator | `validator.py` | Pydantic + range checks (out-of-range → flagged, cleared) |
| Verifier | `verifier.py` | Second pass: per-field confidence, evidence, `needs_review` |

`extract_chart` returns `ExtractionResult`:

- `extraction` — Phase 1 `Extraction`
- `field_confidence` — `dict[str, float]` per field (0.0–1.0)
- `needs_review` — fields below `review_threshold` (default 0.75)
- `evidence` — supporting note snippets per field

## Run locally (stdio)

```bash
# Default: fast offline regex stub
uv run python -m servers.clinical_data

# Agentic prior-auth extractor (requires ANTHROPIC_API_KEY)
EXTRACTOR_BACKEND=real uv run python -m servers.clinical_data
```

Optional chart root override:

```bash
uv run python -m servers.clinical_data --chart-root ./data/charts
# or
CLINICAL_DATA_CHART_ROOT=./data/charts uv run python -m servers.clinical_data
```

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `EXTRACTOR_BACKEND` | `stub` | `stub` (regex, offline) or `real` (agentic prior-auth pipeline) |
| `ANTHROPIC_API_KEY` | — | Required when `EXTRACTOR_BACKEND=real` |
| `CHARTEXTRACT_API_URL` | `https://chartextract.onrender.com` | Oncology API base URL |
| `CLINICAL_DATA_CHART_ROOT` | `./data/charts` | Allowed chart path roots |
| `CLINICAL_DATA_SOURCE` | `mock` | `mock` (offline synthetic patients) or `fhir` (live HAPI via `FHIR_BASE_URL`) |
| `FHIR_BASE_URL` | `http://localhost:8080/fhir` | FHIR server when `CLINICAL_DATA_SOURCE=fhir` |

## Tools

- `get_patient_record(patient_id)` — FHIR Patient JSON (`mock` or `fhir` source)
- `get_patient_observations(patient_id, code?)` — FHIR Observations (LOINC `system|code` when `code` set)
- `get_patient_conditions(patient_id)` — FHIR Conditions
- `get_patient_medications(patient_id)` — FHIR MedicationRequests
- `get_payer_policy(drug, condition)` — Phase 1 `PayerPolicy`
- `extract_chart(note_text | chart_path, drug?, condition?)` — prior-auth `ExtractionResult`
- `extract_oncology_chart(note_text)` — ChartExtractor `ExtractionOutput`

## Resources

- `patient://{patient_id}` — FHIR Patient JSON from the active data source

## Tests

```bash
# Default CI-safe suite (no network)
uv run pytest -m "not network"

# Live API tests (Anthropic + ChartExtractor)
uv run pytest -m network
```
