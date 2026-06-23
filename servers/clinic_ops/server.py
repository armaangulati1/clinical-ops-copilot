"""Clinic-ops MCP server (action side)."""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from servers.clinic_ops.actions import (
    create_task as run_create_task,
)
from servers.clinic_ops.actions import (
    draft_email as run_draft_email,
)
from servers.clinic_ops.actions import (
    schedule_followup as run_schedule_followup,
)
from servers.clinic_ops.actions import (
    send_email as run_send_email,
)
from servers.clinic_ops.config import ServerConfig, load_config
from servers.clinic_ops.errors import ActionFailedError
from servers.clinic_ops.idempotency import IdempotencyStore, InMemoryIdempotencyStore
from servers.clinic_ops.mock_backend import MockBackend
from servers.clinic_ops.schemas import (
    ActionFailure,
    CreateTaskResult,
    EmailDraft,
    ScheduleFollowupResult,
    SendEmailResult,
)

mcp = FastMCP("clinic-ops")
McpContext = Context[Any, Any, Any]
_config: ServerConfig = load_config()
_store: IdempotencyStore = InMemoryIdempotencyStore()
_backend: MockBackend = MockBackend(config=_config, rng=random.Random(_config.rng_seed))


def configure(
    config: ServerConfig,
    *,
    store: IdempotencyStore | None = None,
    backend: MockBackend | None = None,
) -> None:
    """Set runtime configuration and optional test doubles."""
    global _config, _store, _backend
    _config = config
    _store = store or InMemoryIdempotencyStore()
    _backend = backend or MockBackend(
        config=config,
        rng=random.Random(config.rng_seed),
    )


def get_config() -> ServerConfig:
    return _config


def get_store() -> IdempotencyStore:
    return _store


def get_backend() -> MockBackend:
    return _backend


def _tool_error(failure: ActionFailure) -> ToolError:
    return ToolError(failure.model_dump_json())


@mcp.tool()
def draft_email(to: str, subject: str, body: str) -> EmailDraft:
    """Create an email draft without sending."""
    return run_draft_email(to, subject, body)


@mcp.tool()
async def send_email(
    ctx: McpContext,
    to: str,
    subject: str,
    body: str,
    idempotency_key: str,
) -> SendEmailResult:
    """Send an email (mocked) with idempotency and retries."""
    try:
        return await run_send_email(
            to,
            subject,
            body,
            idempotency_key,
            store=_store,
            backend=_backend,
            config=_config,
            ctx=ctx,
        )
    except ActionFailedError as exc:
        raise _tool_error(exc.failure) from exc


@mcp.tool()
async def schedule_followup(
    ctx: McpContext,
    patient_id: str,
    when: datetime,
    note: str,
    idempotency_key: str,
) -> ScheduleFollowupResult:
    """Schedule a patient follow-up (mocked) with idempotency and retries."""
    try:
        return await run_schedule_followup(
            patient_id,
            when,
            note,
            idempotency_key,
            store=_store,
            backend=_backend,
            config=_config,
            ctx=ctx,
        )
    except ActionFailedError as exc:
        raise _tool_error(exc.failure) from exc


@mcp.tool()
async def create_task(
    ctx: McpContext,
    title: str,
    details: str,
    idempotency_key: str,
) -> CreateTaskResult:
    """Create a task/ticket (mocked) with idempotency and retries."""
    try:
        return await run_create_task(
            title,
            details,
            idempotency_key,
            store=_store,
            backend=_backend,
            config=_config,
            ctx=ctx,
        )
    except ActionFailedError as exc:
        raise _tool_error(exc.failure) from exc
