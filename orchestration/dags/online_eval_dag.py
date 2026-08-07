"""Airflow DAG that runs the online evaluation loop on a schedule.

The DAG holds no evaluation logic. Every task is a thin wrapper over one
function in ``online_eval.pipeline``, which is also what the CLI calls, so the
loop is fully testable without an orchestrator and the orchestrator cannot
develop its own behaviour. Adding a metric means editing ``online_eval``; this
file only decides *when* and *in what order*.

Task decomposition, and why it is five tasks and not one::

    simulate_traffic -> sample -> score -> aggregate -> detect_drift -> alert

Splitting on these boundaries buys three things that a single task does not:
a failure tells you which stage broke; ``sample`` and ``score`` are the
retry-safe stages and get retries, while the stages that mutate state are kept
idempotent instead; and a stage can be cleared and re-run from the Airflow UI
without re-running the model traffic in front of it.

The cursor is advanced only by the final task, so a DAG run that dies midway
re-reads the same traffic on the next run rather than skipping it.

Note on ``simulate_traffic``: it is a ``BashOperator`` that shells into the
repository's own virtualenv, not a Python task in the worker. That is not a
workaround, it is the honest shape of the deployment. The eval loop needs only
pydantic; the agent needs a model client, an MCP stack and FHIR libraries. In a
real deployment the application would be a separate service emitting traces and
this task would not exist at all, so it is guarded by a DAG param and can be
switched off.

Directory name: ``orchestration/`` rather than ``airflow/`` on purpose. A
top-level ``airflow/`` package directory shadows the installed ``airflow``
package once the repository root is on ``sys.path``, which breaks every import
in this file in a way that is genuinely annoying to diagnose.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import Param, dag, task

from online_eval.config import OnlineEvalConfig, load_config
from online_eval.pipeline import (
    aggregate_step,
    alert_step,
    detect_step,
    sample_step,
    score_step,
)

REPO_ROOT = Path(
    os.environ.get(
        "CLINICAL_OPS_REPO_ROOT",
        str(Path(__file__).resolve().parents[2]),
    )
)
REPO_PYTHON = os.environ.get(
    "CLINICAL_OPS_REPO_PYTHON",
    str(REPO_ROOT / ".venv" / "bin" / "python"),
)
CONFIG_PATH = os.environ.get("ONLINE_EVAL_CONFIG")

DEFAULT_ARGS = {
    "owner": "clinical-ops-copilot",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
}


def build_config() -> OnlineEvalConfig:
    """Resolve the loop config, with every relative path anchored to the repo.

    Airflow tasks do not run with the repository as the working directory, so a
    relative ``data/online_eval`` would resolve against ``AIRFLOW_HOME`` and the
    loop would quietly read an empty trace store and report "no new traffic"
    forever. Anchoring here is the fix for a failure mode that looks like
    success.
    """
    config = load_config(Path(CONFIG_PATH) if CONFIG_PATH else None)
    updates: dict[str, Any] = {}
    if not config.state_dir.is_absolute():
        updates["state_dir"] = REPO_ROOT / config.state_dir
    if not config.labels_path.is_absolute():
        updates["labels_path"] = REPO_ROOT / config.labels_path
    return config.model_copy(update=updates) if updates else config


@dag(
    dag_id="online_eval_loop",
    description=(
        "Sample traced agent runs, score them, detect regression and drift "
        "against a frozen baseline, and raise alert conditions."
    ),
    schedule="@hourly",
    start_date=datetime(2026, 8, 1),
    catchup=False,
    max_active_runs=1,
    default_args=DEFAULT_ARGS,
    tags=["online-eval", "llm", "observability"],
    params={
        "simulate_traffic_runs": Param(
            30,
            type="integer",
            minimum=0,
            description=(
                "Simulated runs to emit before sampling. Set to 0 when a real "
                "application is emitting traces into the store."
            ),
        ),
        "traffic_profile": Param(
            "steady",
            type="string",
            enum=["steady", "shifted"],
            description=(
                "Case-mix profile for simulated traffic. 'shifted' oversamples "
                "harder cases to exercise the drift detectors."
            ),
        ),
    },
)
def online_eval_loop() -> None:
    simulate_traffic = BashOperator(
        task_id="simulate_traffic",
        bash_command=(
            f"cd {REPO_ROOT} && {REPO_PYTHON} -m online_eval simulate-traffic "
            "--runs {{ params.simulate_traffic_runs }} "
            "--profile {{ params.traffic_profile }} "
            "--seed {{ data_interval_start.int_timestamp if data_interval_start "
            "else 0 }}"
        ),
        # Traffic generation is the demo scaffold, not the loop. If it fails the
        # loop should still score whatever traffic is already in the store.
        retries=1,
    )

    @task(retries=2)
    def sample(**context: Any) -> dict[str, Any]:
        """Pull traced runs newer than the cursor out of the span store."""
        run_id = str(context["run_id"])
        return sample_step(build_config(), cycle_id=run_id)

    @task(retries=2)
    def score(sample_payload: dict[str, Any]) -> dict[str, Any]:
        """Score sampled runs, joining truth for the adjudicated subset."""
        return score_step(build_config(), sample_payload)

    @task
    def aggregate(score_payload: dict[str, Any]) -> dict[str, Any]:
        """Persist runs, compute the cycle and rolling windows, seed baseline."""
        return aggregate_step(build_config(), score_payload)

    @task
    def detect_drift(aggregate_payload: dict[str, Any]) -> dict[str, Any]:
        """Compare the rolling window against the frozen baseline window."""
        return detect_step(build_config(), aggregate_payload)

    @task
    def alert(detect_payload: dict[str, Any]) -> dict[str, Any]:
        """Raise alert conditions, write the cycle record, advance the cursor."""
        result = alert_step(build_config(), detect_payload)
        print(result["summary"])
        return result

    sampled = sample()
    simulate_traffic >> sampled
    alert(detect_drift(aggregate(score(sampled))))


dag_instance = online_eval_loop()
