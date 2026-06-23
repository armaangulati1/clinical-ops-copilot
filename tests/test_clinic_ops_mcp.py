"""MCP integration tests for the clinic-ops server."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import LoggingMessageNotificationParams

from servers.clinic_ops.config import ServerConfig
from servers.clinic_ops.schemas import (
    CreateTaskResult,
    EmailDraft,
    ScheduleFollowupResult,
    SendEmailResult,
)
from servers.clinic_ops.server import configure, get_backend, mcp
from servers.clinic_ops.tool_errors import parse_action_failure_from_tool_text

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fast_server_config() -> ServerConfig:
    config = ServerConfig(
        latency_min_seconds=0.2,
        latency_max_seconds=0.2,
        failure_rate=0.0,
        rng_seed=7,
        mock_timeout_seconds=5.0,
        max_attempts=5,
        backoff_min_seconds=0.01,
        backoff_max_seconds=0.02,
    )
    configure(config)
    get_backend().counters.sends = 0
    return config


@pytest.fixture
async def memory_client(
    fast_server_config: ServerConfig,
) -> AsyncGenerator[ClientSession, None]:
    _ = fast_server_config
    async with create_connected_server_and_client_session(
        mcp,
        raise_exceptions=True,
    ) as session:
        yield session


@pytest.mark.anyio
async def test_memory_client_lists_clinic_ops_tools(
    memory_client: ClientSession,
) -> None:
    tools = await memory_client.list_tools()
    tool_names = {tool.name for tool in tools.tools}
    assert tool_names == {
        "draft_email",
        "send_email",
        "schedule_followup",
        "create_task",
    }


@pytest.mark.anyio
async def test_draft_email_returns_draft(memory_client: ClientSession) -> None:
    result = await memory_client.call_tool(
        "draft_email",
        {
            "to": "patient@example.com",
            "subject": "Prior auth",
            "body": "Please review.",
        },
    )
    assert result.isError is False
    draft = EmailDraft.model_validate(result.structuredContent)
    assert draft.to == "patient@example.com"
    assert draft.draft_id.startswith("draft_")


@pytest.mark.anyio
async def test_send_email_idempotent_via_mcp(memory_client: ClientSession) -> None:
    backend = get_backend()
    backend.counters.sends = 0
    args = {
        "to": "patient@example.com",
        "subject": "Update",
        "body": "Hello",
        "idempotency_key": "mcp-key-1",
    }
    first = await memory_client.call_tool("send_email", args)
    second = await memory_client.call_tool("send_email", args)
    assert first.isError is False
    assert second.isError is False
    parsed_first = SendEmailResult.model_validate(first.structuredContent)
    parsed_second = SendEmailResult.model_validate(second.structuredContent)
    assert parsed_first.message_id == parsed_second.message_id
    assert backend.counters.sends == 1


@pytest.mark.anyio
async def test_slow_tool_emits_progress_and_logs(
    fast_server_config: ServerConfig,
) -> None:
    _ = fast_server_config
    progress_events: list[tuple[float, float | None, str | None]] = []
    log_events: list[LoggingMessageNotificationParams] = []

    async def logging_callback(
        params: LoggingMessageNotificationParams,
    ) -> None:
        log_events.append(params)

    async def progress_callback(
        progress: float,
        total: float | None,
        message: str | None,
    ) -> None:
        progress_events.append((progress, total, message))

    async with create_connected_server_and_client_session(
        mcp,
        logging_callback=logging_callback,
        raise_exceptions=True,
    ) as session:
        result = await session.call_tool(
            "send_email",
            {
                "to": "patient@example.com",
                "subject": "Progress test",
                "body": "Body",
                "idempotency_key": "progress-key",
            },
            progress_callback=progress_callback,
        )

    assert result.isError is False
    assert progress_events, "expected progress notifications"
    assert any(message for _, _, message in progress_events if message)
    assert log_events, "expected logging notifications"


@pytest.mark.anyio
async def test_timeout_surfaces_structured_tool_error(
    memory_client: ClientSession,
) -> None:
    configure(
        ServerConfig(
            latency_min_seconds=1.0,
            latency_max_seconds=1.0,
            failure_rate=0.0,
            mock_timeout_seconds=0.05,
            max_attempts=1,
            backoff_min_seconds=0.01,
            backoff_max_seconds=0.02,
        )
    )
    result = await memory_client.call_tool(
        "send_email",
        {
            "to": "patient@example.com",
            "subject": "Timeout",
            "body": "Body",
            "idempotency_key": "timeout-mcp",
        },
    )
    assert result.isError is True
    assert result.content
    failure = parse_action_failure_from_tool_text(result.content[0].text)  # type: ignore[union-attr]
    assert failure.code == "timeout"


@pytest.mark.anyio
async def test_stdio_client_round_trip(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["CLINIC_OPS_LATENCY_MIN"] = "0"
    env["CLINIC_OPS_LATENCY_MAX"] = "0"
    env["CLINIC_OPS_FAILURE_RATE"] = "0"
    from mcp import StdioServerParameters

    params = StdioServerParameters(
        command="uv",
        args=["run", "python", "-m", "servers.clinic_ops"],
        cwd=PROJECT_ROOT,
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {tool.name for tool in tools.tools} == {
                "draft_email",
                "send_email",
                "schedule_followup",
                "create_task",
            }

            when = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
            schedule_result = await session.call_tool(
                "schedule_followup",
                {
                    "patient_id": "patient-001",
                    "when": when.isoformat(),
                    "note": "Check labs",
                    "idempotency_key": "stdio-sched",
                },
            )
            assert schedule_result.isError is False
            scheduled = ScheduleFollowupResult.model_validate(
                schedule_result.structuredContent
            )
            assert scheduled.patient_id == "patient-001"

            task_result = await session.call_tool(
                "create_task",
                {
                    "title": "PA follow-up",
                    "details": "Call payer",
                    "idempotency_key": "stdio-task",
                },
            )
            assert task_result.isError is False
            task = CreateTaskResult.model_validate(task_result.structuredContent)
            assert task.title == "PA follow-up"
