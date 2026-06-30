# FHIR eval labels — human review (Phase 6)

**Status: CONFIRMED** (`labels_confirmed: true` in `manifest.json`)

## What these labels measure (honest scope)

Each label is derived by applying the **Ozempic / type 2 diabetes payer policy** to the **same structured FHIR facts** the agent reads at runtime (`agent/fhir_facts.py`). This eval measures whether the agent's **decision logic** matches policy-on-FHIR-input. It is **not** independent clinical ground truth. Synthea data is synthetic; **n = 12**.

Derivation code: `evals/fhir/label_derivation.py`

### Policy rules applied

| Rule | Threshold |
|------|-----------|
| Required fields | `a1c_percent`, `metformin_trial_months`, `bmi`, `diabetes_duration_years` |
| Missing any required field | `request-more-info` |
| A1C below threshold | `deny-risk` (< 7.0%) |
| Metformin trial below minimum | `deny-risk` (< 3 months) |
| No T2D Condition in FHIR | `deny-risk` |
| All present and thresholds met | `submit` |

## Proposed labels (confirm or edit `evals/fhir/labels.json`)

| Case | Synthea `patient_id` | Label | A1C | Met (mo) | BMI | Dur (yr) | T2D | Notes |
|------|---------------------|-------|-----|----------|-----|----------|-----|-------|
| case-049 | 110998 | **submit** | 7.92 | 128 | 37.68 | 14 | yes | Only submit in corpus; meets all thresholds |
| case-050 | 103214 | request-more-info | 5.96 | — | 30.08 | — | no | Missing metformin + duration |
| case-051 | 104093 | request-more-info | 5.93 | — | 27.08 | — | no | Missing metformin + duration |
| case-052 | 105572 | request-more-info | 6.08 | — | 20.44 | — | no | Missing metformin + duration |
| case-053 | 106151 | request-more-info | 6.27 | — | 30.34 | — | no | Missing metformin + duration |
| case-054 | 130513 | **deny-risk** | 5.40 | 122 | 27.59 | 32 | yes | A1C < 7.0% |
| case-055 | 132087 | **deny-risk** | 6.08 | 60 | 30.35 | 6 | yes | A1C < 7.0% |
| case-056 | 160804 | **deny-risk** | 5.86 | 129 | 29.43 | 69 | yes | A1C < 7.0% |
| case-057 | 78748 | **deny-risk** | 6.72 | 41 | 32.86 | 3 | yes | A1C < 7.0% (demo patient) |
| case-058 | 10619 | request-more-info | 5.80 | — | 30.27 | — | no | Missing metformin + duration |
| case-059 | 106652 | request-more-info | 6.26 | — | 27.50 | — | no | Missing metformin + duration |
| case-060 | 79440 | request-more-info | 6.99 | — | (varies) | (varies) | yes | Missing metformin only |

### Class distribution

| Label | Count |
|-------|-------|
| submit | 1 |
| deny-risk | 4 |
| request-more-info | 7 |

## After you confirm

1. Set `"labels_confirmed": true` in `evals/fhir/manifest.json`
2. Run: `uv run evals --fhir`

Until confirmed, `uv run evals --fhir` still runs but prints a **PENDING CONFIRMATION** caveat.
