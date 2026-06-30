# FHIR eval: fusion and guardrail deltas

*Source: `evals/results/fhir.json` (post-guardrail, n=12). Pre-guardrail row from the planner-only FHIR-path run on the same held-out set immediately before the deny-risk guardrail extension (Phase 6). Model: `claude-sonnet-4-5`.*

| Comparison | Macro-F1 | request-more-info recall | deny-risk recall | Notes |
|------------|----------|--------------------------|------------------|-------|
| **Note-only baseline** (patient_id cleared) | **0.2456** | 1.000 (7/7) | **0.000 (0/4)** | Sparse notes; misses submit + deny-risk thresholds |
| **FHIR path, planner only** (pre-guardrail) | **0.6866** | **0.286 (2/7)** | **1.000 (4/4)** | 5× `under-request-info`: planner chose deny-risk when fields missing |
| **FHIR path, planner + guardrail** (committed) | **1.0000** | **1.000 (7/7)** | **1.000 (4/4)** | Guardrail routes missing-field deny-risk → request-more-info |

**Fusion delta:** note-only macro-F1 **0.2456** → FHIR-path **1.0000** (same 12 cases; structured FHIR carries signal sparse notes lack).

**Guardrail delta:** request-more-info recall **0.286 → 1.000** on the FHIR path; deny-risk recall **unchanged at 1.000** (legitimate A1C-below-threshold denials pass through).

Cases corrected by guardrail (050, 051, 052, 058, 059): truth `request-more-info`, planner had predicted `deny-risk`.
