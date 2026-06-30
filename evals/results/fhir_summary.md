FHIR-backed prior-auth evaluation
=================================
Labels confirmed: True

CAVEAT: Small n (~12) Synthea patients on local HAPI; not clinical ground truth.
CAVEAT: Labels are derived by applying the Ozempic/T2D payer policy to the same structured FHIR facts the agent reads — a decision-logic eval, not independent chart review.

Prior-auth agent evaluation results
===================================
Cases evaluated: 12
Planner model: claude-sonnet-4-5

Decision accuracy
-----------------
Accuracy:     1.0000
Macro-F1:     1.0000

Per-class precision / recall / F1
  submit                P=1.000  R=1.000  F1=1.000  (n=1)
  request-more-info     P=1.000  R=1.000  F1=1.000  (n=7)
  deny-risk             P=1.000  R=1.000  F1=1.000  (n=4)

Confusion matrix (rows=truth, cols=predicted)
truth \ pred              submit  request-more     deny-risk
submit                         1             0             0
request-more-info              0             7             0
deny-risk                      0             0             4

Trajectory
----------
Trajectory correctness: 100.0%
Hard violations: 0
Warnings (non-failing): 1

Latency & cost
--------------
p50 latency:  13071.0 ms
p95 latency:  15752.3 ms
Avg $/case:   $0.0192

Email judge validation
----------------------
Not run (no drafted emails or judge unavailable).

Notes
-----
- FHIR-backed eval path (CLINICAL_DATA_SOURCE=fhir, live HAPI).
- Patients: 12 Synthea IDs on Ozempic/T2D policy.

Integrity
---------
Labels are read only inside evals/; agent runtime does not access labels.
FHIR eval labels in evals/fhir/labels.json were derived from policy-on-FHIR facts via evals/fhir/label_derivation.py and human-confirmed in LABEL_REVIEW.md.

Comparison: note-only baseline (patient_id cleared, stub extraction)
-------------------------------------------------------------------
Path           Accuracy   Macro-F1
FHIR             1.0000     1.0000
Note-only        0.5833     0.2456

Note-only per-class F1:
  submit               F1=0.000 (n=1)
  request-more-info    F1=0.737 (n=7)
  deny-risk            F1=0.000 (n=4)