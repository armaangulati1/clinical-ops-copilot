# Online evaluation loop (`online_eval/`)

Scores the agent's **traffic**, on a schedule, and alerts when quality regresses
or the traffic population drifts. Orchestrated by an Apache Airflow DAG in
[`orchestration/`](../orchestration/).

## Honest scope, first

**There is no production deployment behind this.** This repository has no users
and no live workload. The traffic this loop scores is **simulated**: synthetic
prior-auth cases replayed through the real agent by
`online_eval/simulated_traffic.py`.

What that means precisely:

| Claim | True here? |
| --- | --- |
| Scores traffic on a schedule rather than a fixed split at CI time | yes |
| Reads decisions out of OpenInference traces, not from the agent | yes |
| Detects regression and drift against a frozen baseline, over a real time series | yes |
| The agent really runs; latency is measured, decisions are not scripted | yes |
| **Monitors a production system with real users** | **no** |
| **Has ever run against real traffic or real PHI** | **no** |
| **Pages a human** | **no.** It writes alert conditions to a log |

Data is synthetic throughout. No PHI exists in this repository, and every value
written to a span passes through `schemas.phi_redaction` before the trace store
ever sees it.

## How this differs from the offline harness

`evals/` and `online_eval/` are not two versions of the same thing.

| | `evals/` (offline) | `online_eval/` (online) |
| --- | --- | --- |
| **Population** | fixed locked split, 16 cases | whatever traffic arrived |
| **Labels** | every case | an adjudicated subset only |
| **When** | at CI time, before merge | on a schedule, after the fact |
| **Question** | "did this change break the agent?" | "is the agent still fine, on today's traffic?" |
| **Failure mode it catches** | a bad commit | a shifted population, a slow slide, a degraded dependency |
| **Output** | pass/fail gate | a time series, a baseline comparison, alerts |

Accuracy is computed by the **same code in both**:
`evals.metrics.classification.compute_classification_metrics`. That is
deliberate. Two independent macro-F1 implementations would eventually disagree,
and then nobody could say which number was right.

## The loop

```
simulate_traffic  ->  sample  ->  score  ->  aggregate  ->  detect_drift  ->  alert
   (the app)          (traces)   (partial   (rolling      (vs frozen       (log +
                                  labels)    window)       baseline)        severity)
```

1. **sample** (`sampling.py`) reads spans newer than a persisted cursor out of
   the trace store, regroups them by `trace_id`, and reconstructs one
   `TracedRun` per trace from the `prior_auth.pipeline` root span that
   `phoenix_obs` already emits. A trace missing its root or its decision action
   is dropped rather than defaulted. Sampling is uniform and seeded.
2. **score** (`scoring.py`) joins ground truth for the adjudicated subset and
   computes per-run signals. Most production traffic is unlabeled, so this is
   modelled honestly: `label_coverage` decides which traces are "adjudicated",
   by a stable hash of the trace id so a run's label status never changes
   between replays.
3. **aggregate** (`scoring.py`, `store.py`) persists scored runs and computes
   two windows: this cycle's runs, and the trailing `window_size` runs across
   all cycles. Detection uses the rolling window.
4. **detect_drift** (`drift.py`) compares the rolling window to the frozen
   baseline.
5. **alert** (`alerts.py`) raises one alert per breached finding, writes the
   cycle record, and advances the cursor.

## What is measured

| Metric | Needs labels? | What it catches |
| --- | --- | --- |
| `macro_f1_regression` | yes | quality dropped vs baseline |
| `macro_f1_floor` | yes | a slow slide that never trips the step delta |
| `low_confidence_rate_rise` | **no** | the planner is hedging more than it used to |
| `guardrail_rate_rise` | **no** | the deterministic guardrail is rewriting more decisions |
| `p95_latency_ratio` | **no** | the pipeline got slower |
| `action_distribution_psi` | **no** | the decision mix shifted, whether or not quality moved |

Four of six need no ground truth, which is the point: in a real deployment
accuracy arrives days later, if at all, and a monitor that can only speak when
labels exist is silent exactly when it is needed.

## Three design decisions worth defending

**The baseline is frozen, not rolling.** The first window that clears the volume
and label minimums is written to `baseline.json` and stays there. A rolling
baseline moves with the drift it is supposed to detect, so a slow degradation
looks normal at every single step. The cost is real: a legitimate permanent
change in traffic keeps alerting until someone resets the baseline on purpose.
That is the trade worth having, because it forces a human decision instead of
quietly absorbing the change.

**"Could not check" is not "checked and fine."** Every finding carries
`comparable` separately from `breached`. When a detector had no baseline, no
labels or too few runs, it reports `comparable=False` and never alerts. A
detector that returned `breached=False` in those states would show a green board
while looking at nothing.

**The cursor advances last.** `sample` reads the high-water mark; `alert` writes
it, after the cycle record is persisted. A run that dies midway re-reads the same
traffic instead of skipping it. Scoring a run twice is harmless; never scoring it
is a blind spot. Appends are deduplicated by `trace_id` so orchestrator retries
cannot double-count.

## Two things this loop got wrong on its first real run

Both are fixed, both have regression tests, and both are the kind of thing that
only shows up when you actually run the thing.

1. **A ratio with no absolute floor alerts on noise.** The first DAG run
   reported a `2.95x` p95 latency regression. It was 0.9ms → 2.7ms of scheduler
   jitter. `p95_latency_floor_ms` now suppresses the ratio below an absolute
   floor, and the detector reports itself as not comparable rather than green or
   red. Test: `test_latency_ratio_is_not_evaluated_below_the_absolute_floor`.
2. **A broken system was allowed to define "normal."** The same run froze a
   baseline whose macro-F1 was 0.2963, below the 0.50 floor, which would have
   anchored the reference window at a failing level permanently. A window now
   has to clear the floor before it can become the baseline. Test:
   `test_a_window_below_the_floor_cannot_become_the_baseline`.

## What the demo actually produced

Five DAG runs on 2026-08-07: three on the `steady` case mix, then two on
`shifted`, which oversamples cases labeled harder. The agent is not touched and
no decision is flipped; only the population it faces changes, which is the most
common real cause of an online regression.

```
cycle                        n  lab   macroF1  lowconf   guard    p95ms  alerts
------------------------------------------------------------------------------
...21:16:37 (steady)        30   12    0.5833    0.367   0.000      1.1       0   <- baseline frozen
...21:16:58 (steady)        60   25    0.5882    0.333   0.000      1.0       0
...21:17:04 (steady)        60   20    0.5326    0.317   0.000      0.9       0
...21:17:09 (shifted)       60   22    0.4717    0.400   0.000      0.8       2
...21:17:14 (shifted)       60   17    0.4095    0.383   0.000      1.0       2
```

```
[CRITICAL] macro_f1_regression: macro-F1 moved -0.1738 against a baseline of
           0.5833 on 17 adjudicated run(s).
[CRITICAL] macro_f1_floor: Rolling macro-F1 0.4095 against a floor of 0.50.
```

Full records: [`orchestration/evidence/`](../orchestration/evidence/).

### What these numbers are not

- **They are not the agent's accuracy.** The traffic runs on the offline
  `StubPlanner`, whose baseline on the locked test split is 0.625; the live
  `claude-sonnet-4-5` planner scores 0.9375 there. The loop is
  planner-agnostic, and running it against the live planner needs only an API
  key, but that has not been done here, so no live-planner online number exists.
- **`guardrail` is 0.000 in every row, and that is structural, not good news.**
  The stub planner never proposes a submit with missing fields, so the
  required-field guardrail has nothing to rewrite. In this configuration the
  guardrail-rate detector is wired and tested but cannot fire, and reading 0.000
  as "the guardrail never had to intervene" would be wrong.
- **`deny-risk` never appears in the action mix**, for the same reason: the stub
  planner only ever emits `submit` or `request-more-info`. So PSI here operates
  over two live classes, not three.
- **The label counts are small** (17-25 adjudicated runs per window). Windows
  below 20 carry an explicit wide-interval note in their own `notes` field.

## Run it

```bash
# One cycle, no orchestrator (same five functions the DAG calls)
python -m online_eval simulate-traffic --runs 30 --profile steady
python -m online_eval cycle
python -m online_eval history

# Exercise the drift detectors with a harder case mix
python -m online_eval simulate-traffic --runs 60 --profile shifted
python -m online_eval cycle

# Start over (keeps the trace store, clears cursor/baseline/history)
python -m online_eval reset
```

On a schedule, under Airflow: see [`orchestration/README.md`](../orchestration/README.md).

## Tests

```bash
uv run pytest tests/test_online_eval_drift.py tests/test_online_eval_loop.py -q
```

- `tests/test_online_eval_drift.py` (22 tests): PSI arithmetic including
  vanished and appeared classes, each regression detector at, above and below
  threshold, and the four states in which a detector must refuse to alert.
- `tests/test_online_eval_loop.py` (38 tests): span reconstruction, the cursor,
  sampling determinism, partial labels, store idempotency, alert severity, the
  five steps including a JSON round trip through every payload (XCom
  serializes), and a full cycle over traffic generated through the real agent.
- `tests/test_online_eval_dag.py` (11 tests): DAG structure. Requires Airflow,
  skips without it.

## Trace sources

The loop reads from an append-only JSONL span store by default: no server, fully
offline, replayable. `sampling.PhoenixSpanSource` is the adapter for reading the
same spans from a live Arize Phoenix instance instead, which is what a
deployment would use. It is lazily imported and **is not exercised by the test
suite**, because it needs a running Phoenix server; do not read its presence as
evidence that a live Phoenix query has been run here.
