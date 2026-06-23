Prior-auth agent evaluation results
===================================
Cases evaluated: 48
Planner model: claude-sonnet-4-5

Decision accuracy
-----------------
Accuracy:     0.8542
Macro-F1:     0.8441

Per-class precision / recall / F1
  submit                P=0.944  R=1.000  F1=0.971  (n=17)
  request-more-info     P=0.714  R=0.938  F1=0.811  (n=16)
  deny-risk             P=1.000  R=0.600  F1=0.750  (n=15)

Confusion matrix (rows=truth, cols=predicted)
truth \ pred              submit  request-more     deny-risk
submit                        17             0             0
request-more-info              1            15             0
deny-risk                      0             6             9

Trajectory
----------
Trajectory correctness: 64.6%
Violations logged: 17

Latency & cost
--------------
p50 latency:  11975.6 ms
p95 latency:  14420.2 ms
Avg $/case:   $0.0177

Email judge validation
----------------------
Validation cases: 8
Exact agreement: 0.000
MAE:             1.375
Pearson r:       -0.293

Error taxonomy (mis-predictions)
--------------------------------
  missed-missing-field: 1
  over-request-info: 6

Notes
-----
- Email judge: live Claude rubric scoring.

Integrity
---------
Labels are read only inside evals/; agent runtime does not access labels.
SEED_SPECS in schemas/seed_data.py informed synthetic case authoring; final labels in data/labels/labels.json were human-confirmed separately. Agent prompts and planner logic do not read labels at runtime.