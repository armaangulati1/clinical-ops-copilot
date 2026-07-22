"""Function-level microbenchmark for the FHIR patient-fetch hot path.

Measures the per-call cost of the two candidate implementations of
``get_patient_record``'s copy step on a real synthetic patient record:

* before: ``Patient.model_validate(record.model_dump(mode="json"))`` -- the
  redundant validate/dump round-trip that ran on every request.
* after:  ``record.model_copy(deep=True)`` -- an isolated deep copy that keeps
  the caller-isolation guarantee without re-running the FHIR validators.

Both operate on a genuine record imported from the service under test
(``servers.clinical_data.patients.PATIENT_RECORDS``), not a synthetic stand-in.

Method: 2000 iterations per implementation, repeated 5 times; the reported
per-call figure is the median across the 5 repeats (median of repeats is robust
to a single noisy run). Run:

    python -m load.microbench

from the repository root, or ``python load/microbench.py``.
"""

from __future__ import annotations

import statistics
import time

from servers.clinical_data.patients import PATIENT_RECORDS

ITERATIONS = 2000
REPEATS = 5


def _first_record():
    """Return one real, already-validated FHIR Patient record."""
    patient_id = sorted(PATIENT_RECORDS.keys())[0]
    return patient_id, PATIENT_RECORDS[patient_id]


def _time_round_trip(record) -> float:
    """Per-call seconds for validate(model_dump(mode='json'))."""
    cls = type(record)
    start = time.perf_counter()
    for _ in range(ITERATIONS):
        cls.model_validate(record.model_dump(mode="json"))
    return (time.perf_counter() - start) / ITERATIONS


def _time_deep_copy(record) -> float:
    """Per-call seconds for model_copy(deep=True)."""
    start = time.perf_counter()
    for _ in range(ITERATIONS):
        record.model_copy(deep=True)
    return (time.perf_counter() - start) / ITERATIONS


def main() -> None:
    patient_id, record = _first_record()

    before_samples = [_time_round_trip(record) for _ in range(REPEATS)]
    after_samples = [_time_deep_copy(record) for _ in range(REPEATS)]

    before = statistics.median(before_samples)
    after = statistics.median(after_samples)
    speedup = before / after

    us = 1_000_000.0
    print("FHIR patient-fetch copy-step microbenchmark")
    print(f"record under test: {patient_id} ({type(record).__name__})")
    print(f"iterations per repeat: {ITERATIONS}, repeats: {REPEATS} (median reported)")
    print()
    print("before samples (us/call): "
          + ", ".join(f"{s * us:.2f}" for s in before_samples))
    print("after  samples (us/call): "
          + ", ".join(f"{s * us:.2f}" for s in after_samples))
    print()
    print(f"model_validate(model_dump(mode='json')) round-trip (before): "
          f"{before * us:.1f} us/call")
    print(f"model_copy(deep=True) (after):                              "
          f"{after * us:.1f} us/call")
    print(f"speedup: {speedup:.2f}x")
    print(f"per-call cost removed: {(before - after) * us:.1f} us")


if __name__ == "__main__":
    main()
