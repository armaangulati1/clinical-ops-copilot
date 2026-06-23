# 2-minute Loom demo script

**Goal:** Show live deployed read server + agent decision + approval gate + audit trail.  
**Total:** ~120 seconds. Record terminal + browser (split or picture-in-picture).

---

## 0:00–0:15 — Hook + live proof

**Screen:** Browser tab on https://clinical-data-mcp.fly.dev/health

**Say:**  
“This is a prior-auth triage copilot. The read-side MCP server is live on Fly — JSON health check, bearer auth on `/mcp`. Decisions are measured on a locked 16-case eval: macro-F1 0.9373, deny-risk recall went from 0.60 to 1.00 after guardrails.”

**Do:** Refresh `/health` once. Optionally open `/metrics` (request counts).

---

## 0:15–0:45 — Agent run against deployed server

**Screen:** Terminal in repo root

**Say:**  
“Locally I run clinic-ops over stdio; clinical-data hits the deployed URL.”

**Do:**

```bash
export CLINICAL_DATA_URL="https://clinical-data-mcp.fly.dev/mcp"
export CLINICAL_DATA_AUTH_TOKEN="<your token>"   # never paste on recording
export EXTRACTOR_BACKEND=stub
export ANTHROPIC_API_KEY="<your key>"

uv run python -m agent --case case-001
```

**Show:** Printed line `case-001: submit (confidence=0.xx)` (or actual output).

**Say:**  
“Two clinical-data tool calls — extract and policy — then the planner returns a schema-valid decision. Run log appends to JSONL.”

**Do:** `tail -1 data/runs/agent_runs.jsonl | python -m json.tool | head -40`  
*(Redact if any PHI-like strings appear; synthetic cases should be safe.)*

---

## 0:45–1:15 — Architecture + safety (quick)

**Screen:** README architecture ASCII or this repo’s `docs/safety.md` skim

**Say:**  
“Read vs write split: clinical-data on HTTP, clinic-ops local. Safety: human approval before send_email, deterministic guardrail blocks submit on missing required fields, PHI redaction on logs, injection guard, chart path sandbox on the server.”

**Optional terminal (5 sec):**

```bash
uv run pytest tests/test_decision_guardrail.py -q
```

---

## 1:15–1:50 — Approval gate in the UI

**Screen:** Terminal + browser

**Do:**

```bash
uv run python -m ui
```

Open **http://127.0.0.1:8080**

**Say:**  
“State-changing actions don’t fire from the planner. They land in a pending queue. I open a case, see proposed clinic-ops action and audit history, approve or reject.”

**Do:**  
- Click a pending approval (or seed one first if queue empty — run a case that proposes `clinic-ops__draft_email` / `send_email` if needed).  
- On detail page, point at **proposed action**, **decision**, **audit events**.  
- Click **Approve** (or show Reject) — narrate that MCP connects on approve.

**If queue empty:** Run `uv run python -m agent --case case-044` (deny-risk often proposes actions) or use a case known to populate the gate from prior session.

---

## 1:50–2:00 — Close

**Screen:** Audit file or UI history

**Do:**

```bash
tail -3 data/runs/audit_trail.jsonl | python -m json.tool
```

**Say:**  
“Append-only audit, eval harness with locked test and regression gate, honest caveats in the README. Code is MIT — link in description.”

**End card (optional):** README results table + live health URL.

---

## Pre-recording checklist

- [ ] `fly scale count 1` confirmed (avoid 421 on MCP)
- [ ] Env vars set off-camera; blur terminal if echoing secrets
- [ ] `data/runs/` writable; at least one pending approval or a case ready to create one
- [ ] Browser zoom 110% for readability
- [ ] Close unrelated tabs/notifications

## After recording

Replace README Loom placeholder:

```markdown
[Demo (2 min)](https://www.loom.com/share/YOUR_ID)
```
