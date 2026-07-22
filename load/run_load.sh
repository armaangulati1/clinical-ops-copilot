#!/usr/bin/env bash
# Load-test driver for clinical-ops-copilot.
#
# Starts the stub-LLM load harness on port 8081 (8080 is taken by a LocalFHIR
# container on the dev machine), runs a discrete VU sweep against the FHIR
# patient path plus the mixed baseline and ramp, and writes raw k6 evidence
# under load/results/<LABEL>/.
#
# Usage:
#   load/run_load.sh before      # profile the current source
#   load/run_load.sh after       # profile after the bottleneck fix
#
# Requires: k6 on PATH, the repo .venv, an already-generated Python env.

set -euo pipefail

LABEL="${1:-run}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PORT="${LOAD_HARNESS_PORT:-8081}"
BASE_URL="http://127.0.0.1:${PORT}"
PYTHON="${REPO_ROOT}/.venv/bin/python"
RESULTS_DIR="${REPO_ROOT}/load/results/${LABEL}"
DURATION="${DURATION:-20s}"
SWEEP_VUS="${SWEEP_VUS:-5 10 20 40 80 120}"

mkdir -p "$RESULTS_DIR"

echo "== Starting load harness on port ${PORT} (stub LLM) =="
"$PYTHON" -m uvicorn load.harness_app:app \
  --host 127.0.0.1 --port "$PORT" --workers 1 --log-level warning \
  > "${RESULTS_DIR}/harness.log" 2>&1 &
HARNESS_PID=$!
trap 'kill "$HARNESS_PID" 2>/dev/null || true' EXIT

# Wait for health.
for _ in $(seq 1 30); do
  if curl -sf "${BASE_URL}/health" > /dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
curl -sf "${BASE_URL}/health" > /dev/null || { echo "harness did not come up"; exit 1; }
echo "harness up (pid ${HARNESS_PID})"

echo "== FHIR patient sweep: VUs [${SWEEP_VUS}], ${DURATION} each =="
for vus in $SWEEP_VUS; do
  echo "-- VUs=${vus} --"
  k6 run \
    -e BASE_URL="$BASE_URL" -e VUS="$vus" -e DURATION="$DURATION" \
    --summary-export "${RESULTS_DIR}/fhir_sweep_vus${vus}.json" \
    load/k6/fhir_sweep.js \
    | tee "${RESULTS_DIR}/fhir_sweep_vus${vus}.txt"
done

echo "== Mixed baseline (10 VUs, 30s) =="
k6 run -e BASE_URL="$BASE_URL" \
  --summary-export "${RESULTS_DIR}/baseline.json" \
  load/k6/baseline.js \
  | tee "${RESULTS_DIR}/baseline.txt"

echo "== Mixed ramp to saturation =="
k6 run -e BASE_URL="$BASE_URL" \
  --summary-export "${RESULTS_DIR}/ramp.json" \
  load/k6/ramp.js \
  | tee "${RESULTS_DIR}/ramp.txt"

echo "== Done. Evidence in ${RESULTS_DIR} =="
