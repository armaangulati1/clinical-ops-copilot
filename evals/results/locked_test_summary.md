Prior-auth agent evaluation results
===================================
Cases evaluated: 16
Planner model: claude-sonnet-4-5

Decision accuracy
-----------------
Accuracy:     0.9375
Macro-F1:     0.9373

Per-class precision / recall / F1
  submit                P=0.857  R=1.000  F1=0.923  (n=6)
  request-more-info     P=1.000  R=0.800  F1=0.889  (n=5)
  deny-risk             P=1.000  R=1.000  F1=1.000  (n=5)

Confusion matrix (rows=truth, cols=predicted)
truth \ pred              submit  request-more     deny-risk
submit                         6             0             0
request-more-info              1             4             0
deny-risk                      0             0             5

Trajectory
----------
Trajectory correctness: 68.8%
Hard violations: 5
Warnings (non-failing): 1

Latency & cost
--------------
p50 latency:  10498.1 ms
p95 latency:  13328.4 ms
Avg $/case:   $0.0175

Email judge validation
----------------------
Not run (no drafted emails or judge unavailable).

Error taxonomy (mis-predictions)
--------------------------------
  missed-missing-field: 1

Notes
-----
- Eval split: evals/splits/locked_test.json (16 cases)

Integrity
---------
Labels are read only inside evals/; agent runtime does not access labels.
SEED_SPECS in schemas/seed_data.py informed synthetic case authoring; final labels in data/labels/labels.json were human-confirmed separately. Agent prompts and planner logic do not read labels at runtime.