# Agent orchestrator

MCP client that connects to **clinical-data** and **clinic-ops**, runs the prior-auth
workflow, and emits schema-valid `Decision` objects with proposed (not executed)
clinic-ops actions.

## Workflow per case

1. `clinical-data__extract_chart` → `ExtractionResult`
2. `clinical-data__get_payer_policy` → `PayerPolicy`
3. Claude plans a `Decision` (with optional `proposed_action`)
4. Structured JSONL run log written (audit trail seed for Phase 5 / evals)

Phase 4 **does not execute** clinic-ops state-changing tools.

## Run

```bash
# Requires ANTHROPIC_API_KEY and uses real prior-auth extractor by default
export ANTHROPIC_API_KEY=your-key-here

# 10 held-out evaluation cases
uv run python -m agent --held-out

# Specific cases
uv run python -m agent --cases case-001,case-002
uv run python -m agent --case case-001
```

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `ANTHROPIC_API_KEY` | — | Required for live runs |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` | Planner model |
| `CLINICAL_DATA_URL` | — | If set, clinical-data over StreamableHTTP (e.g. Fly) |
| `CLINICAL_DATA_AUTH_TOKEN` | — | Bearer token when using `CLINICAL_DATA_URL` |
| `EXTRACTOR_BACKEND` | `real` | Passed to clinical-data server |
| `AGENT_RUNS_DIR` | `data/runs` | JSONL run log directory |

## Run logs

Append-only JSON lines: `data/runs/agent_runs.jsonl`

Each line includes tool-call sequence (tool, args summary, result summary, timing)
and the final `Decision`.

## Tests

```bash
# Offline wiring test
uv run pytest tests/test_agent_wiring.py -q

# Held-out cases (network; skips without API key)
uv run pytest tests/test_agent_held_out.py -m network -q
```
