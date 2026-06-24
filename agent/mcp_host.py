"""MCP client host for clinical-data and clinic-ops servers."""

from __future__ import annotations

import os
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import MCP_DEFAULT_SSE_READ_TIMEOUT
from mcp.types import Tool

from agent.config import (
    CLINIC_OPS_SERVER,
    CLINICAL_DATA_SERVER,
    AgentConfig,
)
from schemas.phi_redaction import redact_payload, redact_secret_values
from servers.clinical_data.path_security import (
    PathNotAccessibleError,
    assert_path_allowed,
)

TOOL_SEPARATOR = "__"


@dataclass(frozen=True)
class DiscoveredTool:
    """A tool discovered from an MCP server."""

    server: str
    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def qualified_name(self) -> str:
        return qualify_tool(self.server, self.name)


def qualify_tool(server: str, tool_name: str) -> str:
    return f"{server}{TOOL_SEPARATOR}{tool_name}"


def split_qualified_tool(qualified_name: str) -> tuple[str, str]:
    if TOOL_SEPARATOR not in qualified_name:
        msg = f"Invalid qualified tool name: {qualified_name!r}"
        raise ValueError(msg)
    server, tool_name = qualified_name.split(TOOL_SEPARATOR, 1)
    return server, tool_name


class McpHost(Protocol):
    """Interface for MCP tool discovery and invocation."""

    async def list_tools(self) -> list[DiscoveredTool]:
        """Return tools from all connected servers."""

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a namespaced tool and return structured content."""

    async def close(self) -> None:
        """Close underlying MCP sessions."""


@dataclass
class _ServerSession:
    name: str
    session: ClientSession


class StdioMcpHost:
    """Connect clinical-data (stdio or StreamableHTTP) and clinic-ops (stdio)."""

    def __init__(self, sessions: dict[str, ClientSession], config: AgentConfig) -> None:
        self._sessions = sessions
        self._config = config

    @classmethod
    async def connect(cls, config: AgentConfig) -> StdioMcpHost:
        stack = AsyncExitStack()
        sessions: dict[str, ClientSession] = {}

        if config.clinical_data_url:
            if not config.clinical_data_auth_token:
                msg = (
                    "CLINICAL_DATA_AUTH_TOKEN is required when CLINICAL_DATA_URL is set"
                )
                raise ValueError(msg)
            sessions[CLINICAL_DATA_SERVER] = await _connect_clinical_data_http(
                stack,
                url=config.clinical_data_url,
                auth_token=config.clinical_data_auth_token,
            )
            stdio_servers = _clinic_ops_stdio_params(config)
        else:
            stdio_servers = _stdio_server_params(config)

        for server_name, params in stdio_servers.items():
            transport = await stack.enter_async_context(stdio_client(params))
            read, write = transport
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            sessions[server_name] = session

        host = cls(sessions, config)
        host._stack = stack  # type: ignore[attr-defined]
        return host

    async def list_tools(self) -> list[DiscoveredTool]:
        discovered: list[DiscoveredTool] = []
        for server_name, session in self._sessions.items():
            listing = await session.list_tools()
            for tool in listing.tools:
                discovered.append(_discovered_from_mcp(server_name, tool))
        return discovered

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> Any:
        _validate_chart_path(arguments, self._config)
        server_name, tool_name = split_qualified_tool(qualified_name)
        session = self._sessions[server_name]
        result = await session.call_tool(tool_name, arguments)
        if result.isError:
            msg = _tool_error_text(result)
            raise RuntimeError(msg)
        return result.structuredContent

    async def close(self) -> None:
        await self._stack.aclose()  # type: ignore[attr-defined]


def _discovered_from_mcp(server_name: str, tool: Tool) -> DiscoveredTool:
    schema = tool.inputSchema
    if not isinstance(schema, dict):
        schema = {}
    return DiscoveredTool(
        server=server_name,
        name=tool.name,
        description=tool.description or "",
        input_schema=schema,
    )


def _tool_error_text(result: object) -> str:
    content = getattr(result, "content", None)
    if content:
        first = content[0]
        text = getattr(first, "text", None)
        if isinstance(text, str):
            return text
    return "MCP tool call failed"


def _server_params(config: AgentConfig) -> dict[str, StdioServerParameters]:
    """Stdio parameters for both MCP servers (local development)."""
    return _stdio_server_params(config)


def _stdio_server_params(config: AgentConfig) -> dict[str, StdioServerParameters]:
    base_env = os.environ.copy()
    clinical_env = {
        **base_env,
        "EXTRACTOR_BACKEND": config.extractor_backend,
    }
    clinic_ops_env = {
        **base_env,
        "CLINIC_OPS_LATENCY_MIN": config.clinic_ops_latency_min,
        "CLINIC_OPS_LATENCY_MAX": config.clinic_ops_latency_max,
        "CLINIC_OPS_FAILURE_RATE": config.clinic_ops_failure_rate,
    }
    return {
        CLINICAL_DATA_SERVER: StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "servers.clinical_data"],
            cwd=str(config.project_root),
            env=clinical_env,
        ),
        CLINIC_OPS_SERVER: StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "servers.clinic_ops"],
            cwd=str(config.project_root),
            env=clinic_ops_env,
        ),
    }


def _clinic_ops_stdio_params(config: AgentConfig) -> dict[str, StdioServerParameters]:
    params = _stdio_server_params(config)
    return {CLINIC_OPS_SERVER: params[CLINIC_OPS_SERVER]}


async def _connect_clinical_data_http(
    stack: AsyncExitStack,
    *,
    url: str,
    auth_token: str | None,
) -> ClientSession:
    if not auth_token:
        msg = "clinical-data HTTP requires CLINICAL_DATA_AUTH_TOKEN"
        raise ValueError(msg)
    client = _clinical_data_http_client(auth_token)
    await stack.enter_async_context(client)
    transport = await stack.enter_async_context(
        streamable_http_client(url, http_client=client),
    )
    read, write, _get_session_id = transport
    session = await stack.enter_async_context(ClientSession(read, write))
    await session.initialize()
    return session


def _clinical_data_http_client(auth_token: str) -> httpx.AsyncClient:
    """HTTP client tuned for Fly edge (avoid HTTP/2 connection coalescing 421s)."""
    return httpx.AsyncClient(
        headers={
            "Authorization": f"Bearer {auth_token}",
            "Connection": "close",
        },
        timeout=httpx.Timeout(60.0, read=MCP_DEFAULT_SSE_READ_TIMEOUT),
        http2=False,
        limits=httpx.Limits(max_keepalive_connections=0, max_connections=10),
    )


def _validate_chart_path(arguments: dict[str, Any], config: AgentConfig) -> None:
    if config.clinical_data_url is not None:
        return
    chart_path = arguments.get("chart_path")
    if chart_path is None:
        return
    chart_roots = (config.project_root / "data" / "charts",)
    if not isinstance(chart_path, str):
        msg = "chart_path must be a string"
        raise ValueError(msg)
    assert_path_allowed(chart_path, chart_roots)


def summarize_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    """Trim and redact argument payloads for audit logs."""
    summary: dict[str, Any] = {}
    for key, value in arguments.items():
        if key in {"note_text", "body", "clinical_note"} and isinstance(value, str):
            summary[key] = f"<text len={len(value)}>"
        else:
            summary[key] = redact_value_for_log(value, field_name=key)
    return redact_payload(summary)


def summarize_result(result: Any) -> dict[str, Any]:
    """Trim and redact tool results for audit logs."""
    if result is None:
        return {}
    if isinstance(result, dict):
        summary = redact_payload(dict(result))
        extraction = summary.get("extraction")
        if isinstance(extraction, dict):
            summary["extraction"] = {
                key: extraction.get(key)
                for key in (
                    "patient_name",
                    "das28_score",
                    "a1c_percent",
                    "migraine_days_per_month",
                    "age",
                )
                if key in extraction
            }
        return summary
    return {"value": redact_secret_values(str(result))}


def redact_value_for_log(value: Any, *, field_name: str | None = None) -> Any:
    from schemas.phi_redaction import redact_value

    return redact_value(value, field_name=field_name)


class MockMcpHost:
    """In-memory MCP host for offline agent wiring tests."""

    def __init__(
        self,
        *,
        extraction_payload: dict[str, Any],
        policy_payload: dict[str, Any],
        clinic_ops_tools: list[DiscoveredTool] | None = None,
        config: AgentConfig | None = None,
    ) -> None:
        self._extraction_payload = extraction_payload
        self._policy_payload = policy_payload
        self._clinic_ops_tools = clinic_ops_tools or _default_clinic_ops_tools()
        self._config = config
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.clinic_ops_counters: dict[str, int] = {}

    async def list_tools(self) -> list[DiscoveredTool]:
        clinical_tools = [
            DiscoveredTool(
                server=CLINICAL_DATA_SERVER,
                name="extract_chart",
                description="Extract prior-auth fields",
                input_schema={"type": "object", "properties": {}},
            ),
            DiscoveredTool(
                server=CLINICAL_DATA_SERVER,
                name="get_payer_policy",
                description="Get payer policy",
                input_schema={"type": "object", "properties": {}},
            ),
        ]
        return clinical_tools + self._clinic_ops_tools

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> Any:
        if self._config is not None:
            try:
                _validate_chart_path(arguments, self._config)
            except PathNotAccessibleError as exc:
                raise RuntimeError(str(exc)) from exc
        self.calls.append((qualified_name, arguments))
        if qualified_name.endswith(f"{TOOL_SEPARATOR}extract_chart"):
            return self._extraction_payload
        if qualified_name.endswith(f"{TOOL_SEPARATOR}get_payer_policy"):
            return self._policy_payload
        if qualified_name.startswith(f"{CLINIC_OPS_SERVER}{TOOL_SEPARATOR}"):
            tool_name = qualified_name.split(TOOL_SEPARATOR, 1)[1]
            self.clinic_ops_counters[tool_name] = (
                self.clinic_ops_counters.get(tool_name, 0) + 1
            )
            return {
                "ok": True,
                "tool": tool_name,
                "invocation": self.clinic_ops_counters[tool_name],
            }
        msg = f"Unexpected mock tool call: {qualified_name}"
        raise RuntimeError(msg)

    async def close(self) -> None:
        return None


def _default_clinic_ops_tools() -> list[DiscoveredTool]:
    names = ("draft_email", "send_email", "schedule_followup", "create_task")
    return [
        DiscoveredTool(
            server=CLINIC_OPS_SERVER,
            name=name,
            description=f"clinic-ops {name}",
            input_schema={"type": "object", "properties": {}},
        )
        for name in names
    ]
