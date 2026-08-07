"""DAG-integrity tests for the online-eval Airflow DAG.

These assert the DAG's *structure*, which is the part a reader of the README has
to take on trust otherwise: that it parses with no import errors, that it has
exactly the tasks and edges claimed, and that retries and scheduling are
actually configured rather than left at defaults.

Airflow is an optional extra (``uv sync --extra orchestration``), so these skip
cleanly when it is not installed. CI installs only the dev group, so this file
skips there; it is exercised locally against the same Airflow the DAG runs on.
Read a skip as "not checked here", never as "passed".
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("airflow", reason="Airflow is the optional 'orchestration' extra")

from airflow.models.dagbag import DagBag  # noqa: E402

DAG_ID = "online_eval_loop"
DAGS_FOLDER = Path(__file__).resolve().parents[1] / "orchestration" / "dags"

EXPECTED_TASKS = {
    "simulate_traffic",
    "sample",
    "score",
    "aggregate",
    "detect_drift",
    "alert",
}

# The loop, in order. Each entry is (upstream, downstream).
EXPECTED_EDGES = {
    ("simulate_traffic", "sample"),
    ("sample", "score"),
    ("score", "aggregate"),
    ("aggregate", "detect_drift"),
    ("detect_drift", "alert"),
}


@pytest.fixture(scope="module")
def dagbag() -> DagBag:
    return DagBag(dag_folder=str(DAGS_FOLDER), include_examples=False)


def test_dag_folder_imports_without_errors(dagbag: DagBag) -> None:
    assert dagbag.import_errors == {}


def test_dag_is_registered(dagbag: DagBag) -> None:
    assert DAG_ID in dagbag.dags


def test_dag_has_exactly_the_expected_tasks(dagbag: DagBag) -> None:
    dag = dagbag.dags[DAG_ID]
    assert set(dag.task_dict) == EXPECTED_TASKS


def test_dag_edges_are_the_claimed_pipeline(dagbag: DagBag) -> None:
    """sample -> score -> aggregate -> detect_drift -> alert, fed by traffic."""
    dag = dagbag.dags[DAG_ID]
    edges = {
        (task.task_id, downstream)
        for task in dag.tasks
        for downstream in task.downstream_task_ids
    }
    assert edges == EXPECTED_EDGES


def test_alert_is_the_only_leaf(dagbag: DagBag) -> None:
    """The cursor advances in the last task, so there must be exactly one."""
    dag = dagbag.dags[DAG_ID]
    leaves = {task.task_id for task in dag.tasks if not task.downstream_task_ids}
    assert leaves == {"alert"}


def test_dag_is_scheduled_and_does_not_backfill(dagbag: DagBag) -> None:
    """Hourly, and no catchup.

    ``schedule_interval`` was removed in Airflow 3, so the schedule is read off
    the timetable. Catchup matters more than it looks: with it on, enabling this
    DAG would backfill one run per hour since the start date, and every one of
    them would score the same trace store and fight over the same cursor.
    """
    dag = dagbag.dags[DAG_ID]
    assert dag.timetable.summary == "0 * * * *"
    assert dag.catchup is False


def test_only_one_run_at_a_time(dagbag: DagBag) -> None:
    """Concurrent runs would race the cursor and the append-only stores."""
    assert dagbag.dags[DAG_ID].max_active_runs == 1


def test_every_task_has_retries_configured(dagbag: DagBag) -> None:
    dag = dagbag.dags[DAG_ID]
    for task in dag.tasks:
        assert task.retries >= 1, f"{task.task_id} has no retries"


def test_retryable_stages_get_more_than_one_retry(dagbag: DagBag) -> None:
    dag = dagbag.dags[DAG_ID]
    assert dag.task_dict["sample"].retries >= 2
    assert dag.task_dict["score"].retries >= 2


def test_traffic_simulation_is_parameterised(dagbag: DagBag) -> None:
    """It must be switchable off, since real traffic needs no simulator."""
    params = dagbag.dags[DAG_ID].params
    assert "simulate_traffic_runs" in params
    assert "traffic_profile" in params


def test_dag_is_tagged_for_discovery(dagbag: DagBag) -> None:
    assert "online-eval" in dagbag.dags[DAG_ID].tags
