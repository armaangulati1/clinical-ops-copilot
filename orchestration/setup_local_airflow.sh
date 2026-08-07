#!/usr/bin/env bash
# Create a standalone Apache Airflow virtualenv for the online-eval DAG.
#
# Airflow lives in its own venv on purpose: it cannot be resolved alongside this
# project's agent dependencies (see requirements-airflow.txt for the specifics).
# The DAG only needs pydantic to run the loop, and shells into the repo's own
# .venv for the one task that drives the agent.
#
# Usage:
#   ./orchestration/setup_local_airflow.sh
#   source orchestration/airflow_env.sh
#   airflow dags test online_eval_loop
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AIRFLOW_VENV="${REPO_ROOT}/.venv-airflow"
AIRFLOW_VERSION="3.0.3"
PYTHON_VERSION="3.11"
CONSTRAINTS="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYTHON_VERSION}.txt"

echo "==> Creating ${AIRFLOW_VENV} (Python ${PYTHON_VERSION})"
if command -v uv >/dev/null 2>&1; then
  uv venv --python "${PYTHON_VERSION}" "${AIRFLOW_VENV}"
  VIRTUAL_ENV="${AIRFLOW_VENV}" uv pip install \
    -r "${REPO_ROOT}/orchestration/requirements-airflow.txt" \
    --constraint "${CONSTRAINTS}"
else
  "python${PYTHON_VERSION}" -m venv "${AIRFLOW_VENV}"
  "${AIRFLOW_VENV}/bin/pip" install --upgrade pip
  "${AIRFLOW_VENV}/bin/pip" install \
    -r "${REPO_ROOT}/orchestration/requirements-airflow.txt" \
    --constraint "${CONSTRAINTS}"
fi

echo "==> Initialising the Airflow metadata database"
AIRFLOW_HOME="${REPO_ROOT}/.airflow" \
  "${AIRFLOW_VENV}/bin/airflow" db migrate >/dev/null

cat <<EOF

Done.

  source orchestration/airflow_env.sh
  airflow dags test online_eval_loop        # run the whole loop once
  airflow standalone                        # scheduler + UI on :8080

The DAG writes loop state to ${REPO_ROOT}/data/online_eval/ (gitignored).
EOF
