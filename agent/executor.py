"""Single execution path for approved clinic-ops actions."""

from __future__ import annotations

from typing import Any

from agent.approval_policy import STATE_CHANGING_CLINIC_OPS_TOOLS
from agent.audit import AuditTrail
from agent.mcp_host import McpHost, qualify_tool, summarize_arguments, summarize_result
from schemas.approval import AuditEventType
from schemas.decisions import ProposedAction


class ActionExecutor:
    """Executes approved clinic-ops tool calls (the only execution path)."""

    def __init__(self, host: McpHost, audit: AuditTrail) -> None:
        self._host = host
        self._audit = audit

    def set_host(self, host: McpHost) -> None:
        self._host = host

    async def execute_approved_action(
        self,
        case_id: str,
        action: ProposedAction,
    ) -> dict[str, Any]:
        """Execute a human-approved clinic-ops action exactly once per call site."""
        if action.server != "clinic-ops":
            msg = f"Only clinic-ops actions may execute; got {action.server!r}"
            raise ValueError(msg)
        if action.tool in STATE_CHANGING_CLINIC_OPS_TOOLS and (
            "idempotency_key" not in action.arguments
        ):
            msg = f"{action.tool} requires idempotency_key"
            raise ValueError(msg)

        qualified = qualify_tool(action.server, action.tool)
        result = await self._host.call_tool(qualified, action.arguments)
        payload = result if isinstance(result, dict) else {"result": result}
        self._audit.append(
            case_id,
            AuditEventType.ACTION_EXECUTED,
            {
                "tool": qualified,
                "arguments_summary": summarize_arguments(action.arguments),
                "result_summary": summarize_result(payload),
            },
        )
        return payload
