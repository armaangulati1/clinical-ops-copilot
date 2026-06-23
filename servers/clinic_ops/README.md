# clinic-ops MCP server

Action-side MCP server for clinic operations: email drafts/sends, follow-up
scheduling, and task creation. External systems are **mocked** in Phase 3 with
configurable latency, failure injection, retries, and idempotency.

## Run locally (stdio)

```bash
uv run python -m servers.clinic_ops
```

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `CLINIC_OPS_LATENCY_MIN` | `0.5` | Min simulated latency (seconds) for slow tools |
| `CLINIC_OPS_LATENCY_MAX` | `3.0` | Max simulated latency (seconds) for slow tools |
| `CLINIC_OPS_FAILURE_RATE` | `0` | Probability of transient mock failure (0.0–1.0) |
| `CLINIC_OPS_RNG_SEED` | — | Seed RNG for deterministic chaos tests |
| `CLINIC_OPS_MOCK_TIMEOUT_SECONDS` | `30` | Per-call timeout for mocked externals |
| `CLINIC_OPS_MAX_ATTEMPTS` | `5` | Max retry attempts (tenacity) |
| `CLINIC_OPS_BACKOFF_MIN` | `0.1` | Min exponential backoff (seconds) |
| `CLINIC_OPS_BACKOFF_MAX` | `2.0` | Max exponential backoff (seconds) |

## Tools

| Tool | Idempotency | Notes |
|------|-------------|-------|
| `draft_email(to, subject, body)` | No | Returns `EmailDraft` only (no send) |
| `send_email(to, subject, body, idempotency_key)` | Yes | Mock send + retries + progress logs |
| `schedule_followup(patient_id, when, note, idempotency_key)` | Yes | Mock scheduling |
| `create_task(title, details, idempotency_key)` | Yes | Mock ticket creation |

State-changing tools return Pydantic result models on success. After retries are
exhausted (or on timeout), the server returns a structured `ActionFailure` JSON
payload in the tool error text.

## Reliability

- **Retries:** `tenacity` exponential backoff on `TransientMockError`
- **Timeouts:** `asyncio.wait_for` on mocked I/O
- **Idempotency:** in-memory store keyed by `(action, idempotency_key)`
- **Progress:** slow tools emit `context.report_progress` and `context.info` /
  `context.debug` for MCP clients

## Tests

```bash
uv run pytest tests/test_clinic_ops_reliability.py tests/test_clinic_ops_mcp.py -q
uv run pytest -m "not network" -q
```
