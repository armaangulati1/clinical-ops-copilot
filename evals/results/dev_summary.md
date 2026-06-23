Prior-auth agent evaluation results
===================================
Cases evaluated: 32
Planner model: claude-sonnet-4-5

Decision accuracy
-----------------
Accuracy:     0.9375
Macro-F1:     0.9364

Per-class precision / recall / F1
  submit                P=1.000  R=1.000  F1=1.000  (n=11)
  request-more-info     P=1.000  R=0.818  F1=0.900  (n=11)
  deny-risk             P=0.833  R=1.000  F1=0.909  (n=10)

Confusion matrix (rows=truth, cols=predicted)
truth \ pred              submit  request-more     deny-risk
submit                        11             0             0
request-more-info              0             9             2
deny-risk                      0             0            10

Trajectory
----------
Trajectory correctness: 75.0%
Hard violations: 8
Warnings (non-failing): 3

Latency & cost
--------------
p50 latency:  12000.8 ms
p95 latency:  14562.4 ms
Avg $/case:   $0.0177

Email judge validation
----------------------
Not run (no drafted emails or judge unavailable).

Error taxonomy (mis-predictions)
--------------------------------
  under-request-info: 2

Notes
-----
- Eval split: evals/splits/dev.json (32 cases)

Integrity
---------
Labels are read only inside evals/; agent runtime does not access labels.
SEED_SPECS in schemas/seed_data.py informed synthetic case authoring; final labels in data/labels/labels.json were human-confirmed separately. Agent prompts and planner logic do not read labels at runtime.