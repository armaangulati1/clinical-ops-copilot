# Environment for running the online-eval DAG locally.
# Usage:  source orchestration/airflow_env.sh
#
# Must be sourced, not executed, since it only exports variables and puts the
# Airflow venv on PATH.

# Resolve this file's own path under both bash and zsh. BASH_SOURCE is unset in
# zsh, and zsh's %x expansion is a parse error in bash, so the zsh branch is
# deferred through eval rather than written literally.
if [ -n "${BASH_SOURCE:-}" ]; then
  _ORCH_SELF="${BASH_SOURCE[0]}"
elif [ -n "${ZSH_VERSION:-}" ]; then
  _ORCH_SELF="$(eval 'echo ${(%):-%x}')"
else
  _ORCH_SELF="$0"
fi

_ORCH_REPO_ROOT="$(cd "$(dirname "${_ORCH_SELF}")/.." && pwd)"

export AIRFLOW_HOME="${_ORCH_REPO_ROOT}/.airflow"
export AIRFLOW__CORE__DAGS_FOLDER="${_ORCH_REPO_ROOT}/orchestration/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES=False

# The DAG module imports online_eval, which lives in the repository root. The
# Airflow venv does not have this project installed, and does not need to: the
# loop's imports stop at pydantic.
export PYTHONPATH="${_ORCH_REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

# Read by the DAG to anchor relative state paths and to find the interpreter
# that can actually run the agent for the traffic-simulation task.
export CLINICAL_OPS_REPO_ROOT="${_ORCH_REPO_ROOT}"
export CLINICAL_OPS_REPO_PYTHON="${_ORCH_REPO_ROOT}/.venv/bin/python"

export PATH="${_ORCH_REPO_ROOT}/.venv-airflow/bin:${PATH}"

unset _ORCH_REPO_ROOT _ORCH_SELF
