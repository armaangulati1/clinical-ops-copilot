# Human approval UI

FastAPI + HTMX interface for the Phase 5 approval gate.

## Run locally

```bash
uv run python -m ui
# or
uv run uvicorn ui.app:app --reload --port 8080
```

Open http://127.0.0.1:8080 for the pending-approval queue.

## Audit history

Programmatic access:

```python
from agent.audit import JsonlAuditTrail, get_case_history
from pathlib import Path

trail = JsonlAuditTrail(Path("data/runs/audit_trail.jsonl"))
events = get_case_history("case-001", trail)
```

Audit file: `data/runs/audit_trail.jsonl` (append-only, PHI-redacted).
