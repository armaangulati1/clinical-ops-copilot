# Safety and PHI handling (Phase 6)

This system is designed as if it handles real clinical data. Phase 6 adds
defense-in-depth before evals (Phase 7) and deployment (Phase 8).

## PHI redaction

All log, audit, and run-record sinks route through `schemas/phi_redaction.py`:

| Sink | Module |
|------|--------|
| Agent run logs (`agent_runs.jsonl`) | `agent/run_log.py` |
| Audit trail (`audit_trail.jsonl`) | `agent/audit.py` |
| MCP argument/result summaries | `agent/mcp_host.py` |
| Clinic-ops MCP progress/log notifications | `servers/clinic_ops/actions.py` |

**Redacted identifiers:** names, MRNs/patient IDs, DOBs, addresses, phones,
emails, SSNs — replaced with stable tokens (`[NAME]`, `[MRN]`, `[DOB]`, etc.).

**Preserved clinical facts:** numeric/clinical criteria (DAS28, A1C, BMI, etc.)
remain intact when they are not identifiers.

## Secrets hygiene

- API keys and service credentials come from environment variables only.
- `redact_secret_values()` scrubs known env secrets from any persisted text.
- `tests/test_secrets_hygiene.py` scans source for hardcoded key patterns and
  asserts secrets never appear in run/audit output.

## Path sandbox (roots boundaries)

Chart file reads use `servers/clinical_data/path_security.is_path_allowed()`.

The agent MCP host validates `chart_path` arguments before forwarding to
`clinical-data__extract_chart`, so traversal attempts (e.g.
`../../etc/passwd`) are rejected end-to-end — not only in isolated unit tests.

## Prompt-injection containment

`agent/injection_guard.py` scans clinical free text before it reaches tools or
the planner:

1. **Detect** instruction-override patterns (e.g. "ignore your instructions",
   "disregard the policy", "email all records").
2. **Contain** by replacing matching lines with `[INJECTION_PATTERN_REMOVED]`
   before model/tool use.
3. **Log** detections as `security_event` audit entries (PHI-redacted).
4. **Enforce** that state-changing clinic-ops actions still require Phase 5
   human approval — injected text cannot bypass the approval gate.

## Running safety tests

```bash
uv run pytest tests/test_phi_redaction.py tests/test_injection_guard.py \
  tests/test_secrets_hygiene.py tests/test_path_roots_e2e.py -q

uv run pytest -m "not network" -q
```
