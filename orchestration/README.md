# Orchestration (`orchestration/`)

Apache Airflow DAG that runs the [online evaluation loop](../online_eval/) on a
schedule.

```
orchestration/
  dags/online_eval_dag.py     the DAG
  setup_local_airflow.sh      creates .venv-airflow and initialises the metadata DB
  airflow_env.sh              source this to get AIRFLOW_HOME, DAGS_FOLDER, PATH
  requirements-airflow.txt    pinned Airflow, and why it is not a project extra
  evidence/                   output of the runs described below
```

## Run it locally

```bash
./orchestration/setup_local_airflow.sh      # one time, ~2 min
source orchestration/airflow_env.sh
airflow dags test online_eval_loop          # executes the whole loop once
```

To exercise the drift detectors with a harder case mix:

```bash
airflow dags test online_eval_loop \
  --conf '{"traffic_profile":"shifted","simulate_traffic_runs":60}'
```

For the scheduler and the web UI on `:8080`:

```bash
airflow standalone
```

Loop state is written to `data/online_eval/` (gitignored). Read the trend with
`python -m online_eval history`.

Verified on Airflow **3.0.3**, Python **3.11.15**, macOS. `airflow dags test`
executes tasks in-process, which is enough to prove the DAG runs; it is not a
substitute for a scheduler under load.

## The DAG

```
simulate_traffic -> sample -> score -> aggregate -> detect_drift -> alert
```

- `schedule="@hourly"`, `catchup=False`, `max_active_runs=1`.
- Default retries 2 with exponential backoff; `sample` and `score` are the
  retry-safe stages, and the stages that mutate state are made idempotent
  instead of being retried blindly.
- `alert` is the only leaf, because it is what advances the cursor.

**The DAG holds no evaluation logic.** Every task is a thin wrapper over one
function in `online_eval.pipeline`, which is also what the CLI calls. Adding a
metric means editing `online_eval/`; this file decides only *when* and *in what
order*. That is what makes the loop testable without an orchestrator.

### Why `simulate_traffic` is a BashOperator

It shells into the repository's own virtualenv rather than running in the
Airflow worker. That is the honest shape of the deployment, not a workaround:
the eval loop needs only pydantic, while the agent needs a model client, an MCP
stack and FHIR libraries. In a real deployment the application would be a
separate service emitting traces and this task would not exist at all, which is
why it is behind a DAG param and can be set to 0 runs.

### Why Airflow lives in its own virtualenv

Airflow 3 and this repository's agent stack pin incompatible fastapi/starlette
ranges. Both directions were tried and both break:

- `apache-airflow` as a project extra invalidates `uv.lock`; the combined
  resolution then fails and takes three unrelated MCP subprocess tests with it.
- Installing `mcp` into an Airflow venv upgrades starlette and Airflow's own API
  server dies with `Router.__init__() got an unexpected keyword argument
  'on_startup'`.

So Airflow is installed separately, against its official constraints file. This
constraint is load-bearing for the design rather than an annoyance: it is the
reason the loop's `sample -> alert` path imports nothing heavier than pydantic,
and that property is asserted by the fact that these tasks run in a venv where
`import mcp` fails.

### Why `orchestration/` and not `airflow/`

A top-level `airflow/` directory shadows the installed `airflow` package as soon
as the repository root is on `sys.path`, which is exactly what the DAG folder
setup does. Every import in the DAG then fails in a way that is genuinely
annoying to diagnose.

## Evidence

[`evidence/`](evidence/) holds the real output, not a transcription:

| File | What it is |
| --- | --- |
| `dag_run_2026-08-07.log` | `airflow dags test` executing all six tasks, `state=success` |
| `cycle_history_2026-08-07.txt` | `python -m online_eval history` across five DAG runs |
| `cycles_2026-08-07.jsonl` | the full cycle records, one JSON object per run |
| `baseline_2026-08-07.json` | the frozen baseline window those cycles were scored against |

**Re-running will not reproduce these exact numbers**, and that is expected
rather than a defect. The traffic generator is seeded from the DAG run's data
interval, so each run draws a different sample of cases; the label subset is
seeded from trace ids, which are new every run. What reproduces is the
*behaviour*: a steady mix holds near the baseline, and a shifted mix drives
macro-F1 down until the regression and floor detectors fire. The committed
files are the record of one dated session, not a golden fixture. The parts that
are pinned deterministically are covered by the test suite instead.

Read [`online_eval/README.md`](../online_eval/README.md#what-the-demo-actually-produced)
for what those numbers do and do not mean. Short version: the traffic is
simulated, it runs on the offline stub planner, and the loop detected a real
regression caused by a real population shift.

## Tests

```bash
source orchestration/airflow_env.sh
pytest tests/test_online_eval_dag.py -q      # 11 DAG-integrity tests
```

They assert the structure the docs claim: no import errors, the exact six tasks,
the exact five edges, one leaf, hourly schedule, catchup off, `max_active_runs`
of 1, and retries actually configured. Airflow is not in the project's dev group,
so this file **skips** under the repo's own venv and in CI. A skip means "not
checked here", never "passed".
