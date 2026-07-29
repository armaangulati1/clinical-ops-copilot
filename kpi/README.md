# KPI harness

Operational KPIs for the prior-auth agent, tracked with the vocabulary a
deployment engineer uses rather than the vocabulary of an ML eval: throughput,
quality, cost, human intervention rate, and cycle time.

The eval harness in [`evals/`](../evals/) answers "is the agent right?". This
layer answers the separate question an owner of a deployed agent has to answer
every week: how fast does it clear work, what does each decision cost, and how
often does a human have to touch it.

Committed report: [`reports/locked_test_kpi.md`](reports/locked_test_kpi.md)
(and the machine-readable `.json` beside it).

## Run it

```bash
uv run kpi report --results evals/results/locked_test.json
```

Writes `kpi/reports/<split>_kpi.md` and `kpi/reports/<split>_kpi.json`.

```bash
uv run kpi report --results evals/results/locked_test.json --check
```

Fails if the committed report differs from a fresh render. This is the CI
gate, so the numbers in the repository cannot silently go stale against the
eval run they came from.

## What each KPI is, precisely

| KPI | Definition | Source |
|---|---|---|
| Throughput | Decisions divided by summed per-decision wall clock. Serial, concurrency 1. | `total_latency_ms` per case |
| Quality | Macro-F1 on the locked held-out split. Read from the eval harness, never recomputed here. | `classification` block |
| Cost | Planner token cost per decision, priced with the repository's own cost helper. | `planner_metrics.usage` per case |
| Human intervention rate | Share of decisions that stop at the human approval gate or are rewritten by the deterministic missing-field guardrail. Union, not sum. | `approval_required`, `guardrail_triggered` per case |
| Cycle time | End-to-end wall clock per decision, p50 and p95. Wider than the harness's planner-only latency block. | `total_latency_ms` per case |

Quality is deliberately a pass-through. If this layer recomputed accuracy it
could drift from the eval harness and put a second, subtly different number
into circulation. Binding to the existing metric makes that impossible.

## Abstention is a first-class result

Every KPI is optional in the report model. When a run does not support a
metric, the report names it under "not computed" with the reason instead of
printing a plausible number. Two cases this actually catches:

- **Cost on an offline stub run.** The stub planner records metrics with zero
  tokens, which would price out at exactly `$0.000000` per decision. That
  reads as a measurement and is not one, so the harness refuses it.
- **Human intervention on an unrecorded run.** Eval artifacts written before
  this instrumentation carry no approval or guardrail outcome. The harness
  says so rather than inferring one from the predicted action.

Adoption is in the KPI list a deployed agent would carry, and it is reported
as not measurable here in every run: this repository is a demo on synthetic
cases with no users and no seats, so adoption has no denominator.

## Instrumentation

`CaseEvalResult` carries two operational fields that the eval harness now
records on every run:

- `approval_required`: the result of `agent.approval_policy.requires_approval`
  on the decision, which is the same pure function the runtime gate uses.
- `guardrail_triggered`: whether the deterministic missing-field guardrail in
  `agent.decision_guardrail` rewrote the decision.

Both default to `None`, meaning "this run did not capture it".

### Backfilling a run recorded before the instrumentation

The committed locked-split run predates these fields. Its outcomes are still
recoverable without re-running any model, because the run log written beside
the eval holds the full decision for every case and the approval policy is
pure:

```bash
uv run kpi backfill \
  --results evals/results/locked_test.json \
  --run-log data/runs/eval/locked_test/agent_runs.jsonl
```

This writes only the two new fields. Predictions, token counts, latencies, and
the macro-F1 are left byte-identical, which was verified by diffing the file
against its pre-backfill copy with the two new keys stripped.

The backfill refuses to run when the run log is not provably the same run: it
requires an entry for every case and requires each recorded action to match
the eval artifact's prediction. A silently mismatched log would put another
run's operational numbers under this run's quality number.

Run logs are gitignored, so the backfill is a local operation. Its output, the
enriched eval artifact, is committed.

## Honest limits

- Synthetic cases. No patient data anywhere in this repository.
- N is 16 decisions on the locked split. Every rate and percentile carries a
  wide interval at that size.
- One sequential run on one developer machine. No concurrency, no queueing, no
  warm-up control, so throughput is a serial figure and not a capacity claim.
- Cost covers planner tokens only. Infrastructure and human review time are
  not priced.
- The guardrail component of the intervention rate fired zero times in the
  recorded run. It is measured and tested, not exercised by this dataset.
