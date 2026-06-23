"""Shared UI / agent dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from agent.approval_store import ApprovalStore, InMemoryApprovalStore
from agent.audit import AuditTrail, JsonlAuditTrail
from agent.config import AgentConfig, load_config
from agent.executor import ActionExecutor
from agent.gate import ApprovalGate
from agent.mcp_host import McpHost, StdioMcpHost


@dataclass
class AppServices:
    """Wired services for the approval UI and agent."""

    config: AgentConfig
    store: ApprovalStore
    audit: AuditTrail
    gate: ApprovalGate
    host: McpHost | None = None


def build_services(
    project_root: Path | None = None,
    *,
    store: ApprovalStore | None = None,
    audit: AuditTrail | None = None,
    host: McpHost | None = None,
) -> AppServices:
    config = load_config(project_root)
    approval_store = store or InMemoryApprovalStore()
    audit_trail = audit or JsonlAuditTrail(config.runs_dir / "audit_trail.jsonl")
    host_for_executor: McpHost = (
        host if host is not None else cast(McpHost, _UnconnectedHost())
    )
    executor = ActionExecutor(host_for_executor, audit_trail)
    gate = ApprovalGate(approval_store, audit_trail, executor)
    return AppServices(
        config=config,
        store=approval_store,
        audit=audit_trail,
        gate=gate,
        host=host,
    )


class _UnconnectedHost:
    """Placeholder until UI connects live MCP servers on approve."""

    async def list_tools(self) -> list[object]:
        return []

    async def call_tool(
        self,
        qualified_name: str,
        arguments: dict[str, object],
    ) -> object:
        msg = "MCP host not connected; launch servers before approving actions"
        raise RuntimeError(msg)

    async def close(self) -> None:
        return None


async def connect_mcp_host(services: AppServices) -> None:
    """Connect stdio MCP servers for action execution."""
    if services.host is not None:
        return
    host = await StdioMcpHost.connect(services.config)
    services.host = host
    services.gate.set_mcp_host(host)
