"""Trajectory scoring rubric for agent run logs.

See `evals/docs/trajectory_rubric.md` for the full specification.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agent.config import CLINIC_OPS_SERVER, CLINICAL_DATA_SERVER
from agent.mcp_host import qualify_tool
from agent.run_log import RunLog
from schemas.decisions import Decision, DecisionAction

EXTRACT_TOOL = qualify_tool(CLINICAL_DATA_SERVER, "extract_chart")
POLICY_TOOL = qualify_tool(CLINICAL_DATA_SERVER, "get_payer_policy")

EXPECTED_TOOL_PREFIX: tuple[str, ...] = (EXTRACT_TOOL, POLICY_TOOL)

# Valid proposed clinic-ops tools per decision (server, tool).
ACCEPTED_PROPOSED_ACTIONS: dict[DecisionAction, frozenset[tuple[str, str]]] = {
    DecisionAction.SUBMIT: frozenset(
        {
            (CLINIC_OPS_SERVER, "create_task"),
            (CLINIC_OPS_SERVER, "send_email"),
            (CLINIC_OPS_SERVER, "schedule_followup"),
        }
    ),
    DecisionAction.REQUEST_MORE_INFO: frozenset(
        {
            (CLINIC_OPS_SERVER, "draft_email"),
            (CLINIC_OPS_SERVER, "send_email"),
        }
    ),
    DecisionAction.DENY_RISK: frozenset(
        {
            (CLINIC_OPS_SERVER, "draft_email"),
            (CLINIC_OPS_SERVER, "send_email"),
            (CLINIC_OPS_SERVER, "create_task"),
        }
    ),
}

# Preferred tools (used only for warning text when a valid variant is used).
PREFERRED_PROPOSED_ACTIONS: dict[DecisionAction, tuple[str, str]] = {
    DecisionAction.SUBMIT: (CLINIC_OPS_SERVER, "create_task"),
    DecisionAction.REQUEST_MORE_INFO: (CLINIC_OPS_SERVER, "draft_email"),
    DecisionAction.DENY_RISK: (CLINIC_OPS_SERVER, "draft_email"),
}


class TrajectoryViolation(BaseModel):
    case_id: str
    reason: str


class TrajectoryScore(BaseModel):
    case_id: str
    correct: bool
    violations: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def score_trajectory(run_log: RunLog, decision: Decision | None) -> TrajectoryScore:
    """Score whether tool calls follow the expected prior-auth workflow."""
    violations: list[str] = []
    warnings: list[str] = []
    tools_called = [record.tool for record in run_log.tool_calls]

    if len(tools_called) < len(EXPECTED_TOOL_PREFIX):
        violations.append(
            f"expected at least {len(EXPECTED_TOOL_PREFIX)} tool calls, "
            f"got {len(tools_called)}"
        )
    else:
        for index, expected in enumerate(EXPECTED_TOOL_PREFIX):
            actual = tools_called[index]
            if actual != expected:
                violations.append(
                    f"step {index + 1}: expected {expected}, got {actual}"
                )

    clinic_ops_called = [
        tool for tool in tools_called if tool.startswith(f"{CLINIC_OPS_SERVER}__")
    ]
    if clinic_ops_called:
        violations.append(
            "clinic-ops tools must not execute during planning "
            f"(found: {', '.join(clinic_ops_called)})"
        )

    if decision is None:
        violations.append("missing final decision in run log")
    elif decision.proposed_action is not None:
        proposed = decision.proposed_action
        pair = (proposed.server, proposed.tool)
        accepted = ACCEPTED_PROPOSED_ACTIONS.get(decision.action, frozenset())
        preferred = PREFERRED_PROPOSED_ACTIONS.get(decision.action)
        if pair not in accepted:
            violations.append(
                f"proposed_action {proposed.server}/{proposed.tool} is not an "
                f"accepted clinic-ops action for {decision.action.value}"
            )
        elif preferred is not None and pair != preferred:
            warnings.append(
                f"proposed_action {proposed.server}/{proposed.tool} is valid but "
                f"preferred {preferred[0]}/{preferred[1]} for "
                f"{decision.action.value}"
            )

    return TrajectoryScore(
        case_id=run_log.case_id,
        correct=not violations,
        violations=violations,
        warnings=warnings,
    )


def aggregate_trajectory_scores(scores: list[TrajectoryScore]) -> float:
    """Return core trajectory-correctness percentage (0-100); warnings allowed."""
    if not scores:
        return 0.0
    correct = sum(1 for score in scores if score.correct)
    return round(100.0 * correct / len(scores), 2)
