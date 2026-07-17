# Arize Phoenix observability layer (`phoenix_obs/`)

I instrumented my existing prior-auth agent with **Arize Phoenix**. Demo scope,
self-authored synthetic data. Phoenix is an open-source LLM observability and
evaluation library (`pip install arize-phoenix`); this is an **independent
demonstration** of instrumenting a real agent with it. It is **not** production
observability, and it is not affiliated with or endorsed by Arize. Phoenix
here runs entirely locally: no external service and no cloud account.

## What this does

1. **Traces the real pipeline.** The agent's router/planner, MCP tool calls
   (chart extractor + payer policy), the required-field guardrail, and the final
   decision are emitted as [OpenInference](https://github.com/Arize-ai/openinference)
   spans (the tracing format Phoenix ingests) over OpenTelemetry.
2. **Runs a Phoenix eval and compares it to the repo's own harness.** The same
   locked test split is run through the instrumented pipeline; the
   `decision_correctness` dimension is scored from the trace and compared
   case-for-case to this repo's hand-rolled eval harness (`evals/`).
3. **Ships deterministic offline tests** for the instrumentation layer (span
   presence, span-kind/attribute correctness, no-PHI-in-traces) wired into the
   existing suite so CI stays green with only light OpenTelemetry deps.

## The agent code is not modified

The decision logic under `agent/` is byte-for-byte unchanged. Instrumentation
happens **at the boundary**, exactly like the HL7 ingestion layer precedent:

- `agent.runner.run_case` already accepts its `McpHost` and `PlannerLlm` as
  injected dependencies. `TracedMcpHost` and `TracedPlanner` wrap those two
  seams, so the extractor / payer-policy / planner spans are **real
  call-wrapping spans** produced without touching `run_case`.
- The required-field guardrail runs *inside* `run_case` and is not an injected
  seam. Rather than reach into agent internals, its span is **reconstructed from
  the run's PHI-redacted audit payload** (`agent.run_log.RunLog.guardrail_event`),
  the same audit trail the agent already persists. This is called out on the
  span itself (`guardrail.source = "run_log.guardrail_event"`) so the trace is
  never mistaken for a deeper hook than it is.

Proof the agent tree is unmodified on this branch:

```
git diff --stat origin/main..phoenix-observability -- agent/    # empty
```

## Span list (one case run)

| span | OpenInference kind | how it is produced |
| --- | --- | --- |
| `prior_auth.pipeline` | `CHAIN` | root span opened by `traced_run_case`; carries the final `decision.action` |
| `mcp.tool.extract_chart` | `TOOL` | real wrap of `McpHost.call_tool` |
| `mcp.tool.get_payer_policy` | `TOOL` | real wrap of `McpHost.call_tool` |
| `planner.plan_decision` | `LLM` | real wrap of `PlannerLlm.plan_decision` (records model + total tokens when live) |
| `guardrail.required_field` | `GUARDRAIL` | reconstructed from `run_log.guardrail_event` |

## No PHI in traces

Every value written to a span (tool inputs/outputs, planner input, decision
rationale) is routed through this repo's own `schemas.phi_redaction` helpers
before serialization. A test seeds a synthetic patient name into a clinical note
and asserts it is absent from every span attribute (and that the `[NAME]`
redaction token appears instead).

## Phoenix eval vs. the repo's harness

Run offline (no server, no key, deterministic):

```
python -m phoenix_obs.eval_driver --in-memory
```

Result on `evals/splits/locked_test.json` (16 cases), using this repo's
**offline `StubPlanner`**, the same deterministic planner the CI eval path uses:

```
Phoenix-view decision accuracy: 0.625 (16 cases)
Harness-view decision accuracy: 0.625 (16 cases)
Per-case view agreement: 16/16
```

**What this validates.** The Phoenix trace-derived view reproduces the
hand-rolled harness's per-case verdicts **exactly (16/16)**. The comparison is a
fidelity check on the instrumentation, not a quality claim: any divergence would
mean a span was capturing something other than the real decision path, and the
driver prints a `DIVERGENCE DETECTED` line if agreement is not N/N.

**On the number itself.** `0.625` is the offline `StubPlanner` baseline, not the
agent's headline accuracy. The live Claude planner (`claude-sonnet-4-5`) scores
**0.9375** on this same locked split (see `evals/results/locked_test_summary.md`).
The instrumentation is planner-agnostic; the identical wrappers trace the live
planner. To reproduce the live number under Phoenix and log per-span
`decision_correctness` scores into a local Phoenix UI:

```
ANTHROPIC_API_KEY=<key> python -m phoenix_obs.eval_driver --phoenix --live
```

### LLM-judge email-quality dimension (pending live run)

A second, LLM-graded dimension (drafted-email quality) requires a live planner
and judge. No `ANTHROPIC_API_KEY` was present in the environment during this
build, so it was **not scored and no numbers are fabricated**. The exact command
above runs it; the driver prints a `PENDING LIVE RUN` notice offline.

## Running the tests

```
pytest tests/test_phoenix_obs.py -q
```

These use an in-memory span exporter, the stub planner, and the mock MCP host,
fully offline and deterministic, no Phoenix server required.

## Install

The instrumentation and its tests need only the light tracing deps (already in
the dev group). The full local UI + eval-annotation client is an optional extra:

```
uv sync --extra phoenix
```
