# Prior-auth copilot: what I built and where it breaks

## The problem

Prior authorization is a real ops tax: clinicians and staff chase payer rules, re-read charts, draft letters, and resubmit when something is missing. It is slow, error-prone, and expensive. The failure modes are not exotic — wrong bucket (submit vs ask for more info vs flag denial risk), missed required fields, and overconfident automation that looks fine until a payer rejects it.

I wanted a small, auditable system that mirrors how a good ops team works: read the chart, check the policy, make a triage decision, propose (not auto-fire) downstream actions, and leave a trace a human can approve.

## Approach

**Split read vs write with MCP.** `clinical-data` is the read side: extract structured fields, fetch payer policy, sandboxed chart paths. `clinic-ops` is the action side: email, tasks, follow-ups. The agent is an MCP client plus a Claude planner — it never bypasses the servers.

**Eval before vibes.** I built an eval harness with stratified dev / locked-test splits (32 / 16 cases), macro-F1 and per-class metrics, a strict trajectory rubric, latency and cost per case, and a regression gate in CI. Labels live in `data/labels/`; the agent does not read them at runtime.

**Safety as plumbing, not a slide.** Human approval gate for state-changing tools. Deterministic guardrail that blocks submit when required policy fields are null or flagged `needs_review`. PHI redaction on logs and audit JSONL. Injection guard on tool arguments. Path sandbox on the server.

**Production shape.** `clinical-data` runs on Fly over stateful StreamableHTTP with bearer auth (`https://clinical-data-mcp.fly.dev/health`). The agent points at that URL; clinic-ops stays local stdio for now.

## Results (committed numbers)

On the **locked test** split (n=16, held out before tuning):

- **Macro-F1: 0.9373** (accuracy 0.9375)
- **Pre-fix full-48 baseline macro-F1: 0.844**
- **deny-risk recall: 1.000** — up from **0.600** after planner + guardrail / prompt fixes
- Per-class F1: submit **0.9231**, request-more-info **0.8889**, deny-risk **1.000**
- **Trajectory correctness: 68.75%** — the rubric is strict on which clinic-ops action maps to which decision; many “warnings” are acceptable variants, but hard violations still count against the headline number
- **Latency p50 / p95: 10,498.08 / 13,328.36 ms**; **avg $0.017478 / case** (Claude planner + tools, locked test run)
- **Reliability:** clinic-ops chaos tests with **30%** injected failure rate — **40/40** idempotent sends and **20/20** action bundles complete with no double-sends (`tests/test_clinic_ops_reliability.py`)

The headline improvement is deny-risk recall. That was the gap that would hurt in production: calling something “submit” when criteria are clearly not met.

## What I would do differently

1. **More real charts, fewer synthetic notes.** Labels are human-confirmed but the corpus is still synthetic. n=16 locked test is honest for a portfolio piece, not for a launch claim.

2. **Calibrate confidence or gate on it.** Errors still land at ~0.95 confidence (e.g. locked `case-039`: predicted submit, truth request-more-info for missing `chronic_migraine_diagnosis`). I added a deterministic guardrail for null/`needs_review` fields, but semantic “missing diagnosis” gaps still slip through.

3. **Fix or drop the email judge.** I validated an LLM judge against 8 human ratings: **0% exact agreement**, MAE **1.38**, Pearson r ≈ **−0.29**. It is excluded from scoring for good reason. I would either retrain the rubric with more human labels or use human spot-checks only.

4. **Deploy clinic-ops and the UI** behind the same auth story, or run actions only in demo mode until that exists.

5. **Trajectory rubric vs planner behavior.** The planner often proposes `draft_email` on submit cases; the rubric prefers other clinic-ops tools. That drives trajectory % down even when decisions are right — I would align prompt, rubric, and product intent once.

## Where it fails (honest)

| Failure | Example / evidence |
|---------|-------------------|
| **Missed “missing field” triage** | Locked `case-039`: submit vs request-more-info when `chronic_migraine_diagnosis` is absent |
| **Overconfidence on errors** | Remaining mis-predictions still ~0.95 confidence (`evals/results/tuning_comparison.md`) |
| **Small locked test** | n=16 → wide confidence intervals; one case flip moves metrics a lot |
| **Synthetic data** | SEED_SPECS informed authoring; labels human-confirmed — still not production charts |
| **Judge miscalibration** | Email quality judge disagrees with humans; not used in automated score |
| **Historical deny-risk weakness** | Full-48 deny-risk recall was **0.600** before fixes — edge cases existed |
| **Stateful MCP ops** | Fly must run **one machine** (`--ha=false`) or sessions 421; not horizontally scaled |
| **Action side local only** | clinic-ops and approval UI are not on Fly yet — demo is split across local + cloud |

## Closing

This is a **workflow copilot with receipts**: MCP boundaries, eval harness, deployed read server, approval gate, and numbers that include the baseline and the failures. It is not a claim that prior auth is “solved.” It is a claim that you can measure, gate, and ship incrementally in a regulated-adjacent domain — and that I know exactly where the remaining 6.25% of locked-test decisions (and 31.25% of strict trajectories) still hurt.
