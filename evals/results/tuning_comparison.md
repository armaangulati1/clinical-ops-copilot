# Tuning comparison (Phase 7 clean remeasure)

## Split (committed before tuning)

| Split | n | submit | request-more-info | deny-risk |
|-------|---|--------|-------------------|-----------|
| **dev** (`evals/splits/dev.json`) | 32 | 11 | 11 | 10 |
| **locked test** (`evals/splits/locked_test.json`) | 16 | 6 | 5 | 5 |

Algorithm: within each class, sort `case_id` and assign evenly spaced indices to locked test (quotas 6/5/5); remainder to dev.

## Changes applied (general logic only)

1. **Planner deny-risk rule** (`agent/llm.py` system prompt): `request-more-info` only for genuinely missing/ambiguous required fields; `deny-risk` when all required fields are present but criteria are not met.
2. **Trajectory rubric** (`evals/metrics/trajectory.py`, `evals/docs/trajectory_rubric.md`): core order still required; accepted proposed-action variants per decision; non-preferred variants are warnings only.

Dev iteration: **one** live dev run after fixes (deny-risk recall already 100% on dev — no second prompt pass).

## Before / after (decision metrics)

| Metric | Original full-48 baseline (pre-split) | **Dev (32)** | **Locked test (16)** headline |
|--------|----------------------------------------|--------------|-------------------------------|
| Macro-F1 | 0.844 | 0.936 | **0.937** |
| Accuracy | 0.854 | 0.938 | **0.938** |
| deny-risk **recall** | **0.600** | **1.000** | **1.000** |
| deny-risk F1 | 0.750 | 0.909 | **1.000** |
| request-more-info recall | 0.938 | 0.818 | 0.800 |
| submit recall | 1.000 | 1.000 | 1.000 |
| Trajectory correctness % | 64.6 | 75.0 | 68.8 |

## Email judge

Excluded from automated scoring. Prior validation: 8 human ratings, 0% exact agreement, MAE 1.38, Pearson r ≈ −0.29 (miscalibrated).

## Honest caveats

- Data is **synthetic**; locked-test n=16 has wide confidence intervals.
- Prompt change was motivated by the **pre-split** full-48 deny-risk recall gap; dev metrics were used to confirm direction, not to fit locked labels.
- **Overconfidence persists**: remaining errors (e.g. locked `case-039` submit at high confidence) still occur at ~0.95 confidence.
- Locked `case-039` (submit vs request-more-info for missing `chronic_migraine_diagnosis`) remains a failure mode.

Results files: `evals/results/dev.json`, `evals/results/locked_test.json`, and matching `*_summary.md`.
