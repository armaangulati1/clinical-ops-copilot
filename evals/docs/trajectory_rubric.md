# Trajectory evaluation rubric

Trajectory scoring measures whether the agent followed the expected **read-side**
workflow before proposing a clinic-ops action.

## Hard requirements (fail trajectory)

1. **Core tool order:** `clinical-data__extract_chart` then
   `clinical-data__get_payer_policy` (first two MCP calls).
2. **No executed clinic-ops tools** during the planning loop (proposals only).
3. **Proposed action must be an accepted variant** for the decision class (see below).
4. A final decision must be present in the run log.

## Warnings (do not fail trajectory)

When the proposed clinic-ops tool is **valid but not preferred**, record a warning
only. Examples:

| Decision | Preferred | Also accepted (warning) |
|----------|-----------|-------------------------|
| submit | `create_task` | `send_email`, `schedule_followup` |
| request-more-info | `draft_email` | `send_email` |
| deny-risk | `draft_email` | `send_email`, `create_task` |

## Reported metric

**Trajectory correctness %** = share of cases with **no hard violations** (warnings
are reported separately and do not reduce the percentage).

Implementation: `evals/metrics/trajectory.py`.
