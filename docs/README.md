# Documentation

Start here depending on who you are.

## If you have 5 minutes (recruiter, founder, PM)

1. [Main README](../README.md) — what this is and why it matters, in plain English
2. [teardown.md](teardown.md) — the written post-mortem: problem, approach, results, and what went wrong
3. [demo_script.md](demo_script.md) — the 2-minute demo shot list (what the Loom shows)

## If you're an engineer evaluating the work

1. [Main README → For Engineers](../README.md#for-engineers) — benchmarks, architecture, run instructions
2. [safety.md](safety.md) — PHI redaction, prompt-injection guards, approval policy
3. [fhir_teardown.md](fhir_teardown.md) — FHIR integration: fusion, guardrail iteration, honest deltas
4. [transport_tradeoff.md](transport_tradeoff.md) — why stateful StreamableHTTP for the deployed MCP server
5. [workflow_spec.md](workflow_spec.md) — the agent workflow specification

## Reference

| Doc | What it covers |
|-----|----------------|
| [teardown.md](teardown.md) | Post-mortem: problem, approach, results, failures |
| [fhir_teardown.md](fhir_teardown.md) | FHIR integration post-mortem with eval deltas |
| [safety.md](safety.md) | PHI handling, injection guards, approval policy |
| [transport_tradeoff.md](transport_tradeoff.md) | MCP transport decision record |
| [workflow_spec.md](workflow_spec.md) | Agent workflow specification |
| [labeling_rubric.md](labeling_rubric.md) | How eval case labels were assigned |
| [deploy_fly.md](deploy_fly.md) | Deploying the clinical-data server to Fly.io |
| [demo_script.md](demo_script.md) | 2-minute Loom recording script |
| [fhir_demo_script.md](fhir_demo_script.md) | 60-second FHIR + provenance demo script |
| [screenshots/](screenshots/) | Approval UI screenshots used in the README |

Eval results live in [`evals/results/`](../evals/results/), including
[tuning_comparison.md](../evals/results/tuning_comparison.md) and
[fhir_guardrail_comparison.md](../evals/results/fhir_guardrail_comparison.md).
