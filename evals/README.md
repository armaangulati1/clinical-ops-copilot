# Evals

Evaluation harness for prior-auth agent quality measurement (Phase 7).

## Splits (dev vs locked test)

Stratified split files (32 dev / 16 locked test):

```bash
# Development tuning (only split you may inspect during tuning)
EXTRACTOR_BACKEND=real uv run evals --split evals/splits/dev.json --skip-judge

# Locked test — run once for headline numbers
EXTRACTOR_BACKEND=real uv run evals --split evals/splits/locked_test.json --skip-judge
```

See `evals/results/tuning_comparison.md` for the latest before/after table.

## Run

```bash
# Live evaluation (default; requires ANTHROPIC_API_KEY)
uv run evals

# Offline baseline (stub planner; for CI/dev)
uv run evals --offline --fixture-judge evals/fixtures/judge_scores.json
```

Results are written to:

- `evals/results/latest.json`
- `evals/results/latest_summary.md`

## Metrics

| Metric | Module |
|--------|--------|
| Decision accuracy (P/R/F1, macro-F1, confusion matrix) | `evals/metrics/classification.py` |
| Error taxonomy | `evals/metrics/errors.py` |
| Trajectory correctness | `evals/metrics/trajectory.py` |
| Latency p50/p95, $/case | `evals/metrics/latency.py` + `schemas/run_metrics.py` |
| Email judge agreement | `evals/metrics/judge_agreement.py` |

## Integrity

Held-out labels (`data/labels/labels.json`) are read **only** inside `evals/` (and labeling scripts/tests). Agent runtime code does not access labels.

## CI regression gate

`evals/regression/` contains a 9-case fixture subset and `macro_f1_min: 0.50` threshold. CI runs `tests/test_eval_regression.py` (network-free).

## Offline here, online next door

This harness is **offline**: a fixed labeled split, scored at CI time, as a merge
gate. The separate question of whether the agent is still fine on the traffic it
is actually receiving is answered by [`online_eval/`](../online_eval/), which
samples traced runs, scores them on a schedule, and detects regression and drift
against a frozen baseline. It reuses `evals.metrics.classification` rather than
reimplementing macro-F1, so the two layers cannot disagree about what accuracy
means. Its traffic is simulated; it has never run against a production workload.
