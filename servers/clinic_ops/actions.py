"""Clinic-ops action implementations (mocked externals)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import Context

from schemas.phi_redaction import redact_text
from servers.clinic_ops.config import ServerConfig
from servers.clinic_ops.errors import ActionFailedError
from servers.clinic_ops.idempotency import IdempotencyStore
from servers.clinic_ops.mock_backend import MockBackend, utc_now
from servers.clinic_ops.reliability import execute_with_retries
from servers.clinic_ops.schemas import (
    CreateTaskResult,
    EmailDraft,
    ScheduleFollowupResult,
    SendEmailResult,
)

McpContext = Context[Any, Any, Any]

SEND_EMAIL_ACTION = "send_email"
SCHEDULE_FOLLOWUP_ACTION = "schedule_followup"
CREATE_TASK_ACTION = "create_task"


def draft_email(to: str, subject: str, body: str) -> EmailDraft:
    """Create an email draft without sending."""
    return EmailDraft(
        to=to,
        subject=subject,
        body=body,
        draft_id=f"draft_{uuid.uuid4().hex[:12]}",
    )


async def _report_progress(
    ctx: McpContext | None,
    progress: float,
    total: float,
    message: str,
) -> None:
    if ctx is None:
        return
    await ctx.report_progress(progress, total, redact_text(message))


async def _log_info(ctx: McpContext | None, message: str) -> None:
    if ctx is None:
        return
    await ctx.info(redact_text(message))


async def _log_debug(ctx: McpContext | None, message: str) -> None:
    if ctx is None:
        return
    await ctx.debug(redact_text(message))


async def _log_error(ctx: McpContext | None, message: str) -> None:
    if ctx is None:
        return
    await ctx.error(redact_text(message))


async def send_email(
    to: str,
    subject: str,
    body: str,
    idempotency_key: str,
    *,
    store: IdempotencyStore,
    backend: MockBackend,
    config: ServerConfig,
    ctx: McpContext | None = None,
) -> SendEmailResult:
    """Send email via mock backend with idempotency and retries."""
    _ = body
    cached = store.get(SEND_EMAIL_ACTION, idempotency_key)
    if cached is not None:
        if ctx is not None:
            await _log_info(
                ctx,
                "Returning cached send_email result (idempotent replay)",
            )
        return SendEmailResult.model_validate(cached.payload)

    if ctx is not None:
        await _log_info(ctx, "Starting send_email")
        await _log_debug(ctx, f"idempotency_key={idempotency_key}")

    async def _attempt() -> SendEmailResult:
        await _report_progress(ctx, 0.25, 1.0, "Connecting to mail provider")
        message_id = await backend.send_email_once(to, subject)
        await _report_progress(ctx, 1.0, 1.0, "Email sent")
        return SendEmailResult(
            message_id=message_id,
            to=to,
            subject=subject,
            idempotency_key=idempotency_key,
            sent_at=utc_now(),
        )

    try:
        result = await execute_with_retries(
            SEND_EMAIL_ACTION,
            _attempt,
            config=config,
            idempotency_key=idempotency_key,
        )
    except ActionFailedError:
        if ctx is not None:
            await _log_error(ctx, "send_email failed after retries")
        raise

    store.put(SEND_EMAIL_ACTION, idempotency_key, result.model_dump(mode="json"))
    if ctx is not None:
        await _log_info(ctx, f"send_email complete: message_id={result.message_id}")
    return result


async def schedule_followup(
    patient_id: str,
    when: datetime,
    note: str,
    idempotency_key: str,
    *,
    store: IdempotencyStore,
    backend: MockBackend,
    config: ServerConfig,
    ctx: McpContext | None = None,
) -> ScheduleFollowupResult:
    """Schedule a follow-up via mock backend with idempotency and retries."""
    cached = store.get(SCHEDULE_FOLLOWUP_ACTION, idempotency_key)
    if cached is not None:
        if ctx is not None:
            await _log_info(ctx, "Returning cached schedule_followup result")
        return ScheduleFollowupResult.model_validate(cached.payload)

    if ctx is not None:
        await _log_info(ctx, "Starting schedule_followup")

    async def _attempt() -> ScheduleFollowupResult:
        await _report_progress(ctx, 0.25, 1.0, "Opening scheduling system")
        followup_id = await backend.schedule_followup_once(patient_id, when, note)
        await _report_progress(ctx, 1.0, 1.0, "Follow-up scheduled")
        return ScheduleFollowupResult(
            followup_id=followup_id,
            patient_id=patient_id,
            when=when,
            note=note,
            idempotency_key=idempotency_key,
        )

    try:
        result = await execute_with_retries(
            SCHEDULE_FOLLOWUP_ACTION,
            _attempt,
            config=config,
            idempotency_key=idempotency_key,
        )
    except ActionFailedError:
        if ctx is not None:
            await _log_error(ctx, "schedule_followup failed after retries")
        raise

    store.put(
        SCHEDULE_FOLLOWUP_ACTION,
        idempotency_key,
        result.model_dump(mode="json"),
    )
    return result


async def create_task(
    title: str,
    details: str,
    idempotency_key: str,
    *,
    store: IdempotencyStore,
    backend: MockBackend,
    config: ServerConfig,
    ctx: McpContext | None = None,
) -> CreateTaskResult:
    """Create a task/ticket via mock backend with idempotency and retries."""
    cached = store.get(CREATE_TASK_ACTION, idempotency_key)
    if cached is not None:
        if ctx is not None:
            await _log_info(ctx, "Returning cached create_task result")
        return CreateTaskResult.model_validate(cached.payload)

    if ctx is not None:
        await _log_info(ctx, "Starting create_task")

    async def _attempt() -> CreateTaskResult:
        await _report_progress(ctx, 0.25, 1.0, "Opening ticketing system")
        task_id = await backend.create_task_once(title, details)
        await _report_progress(ctx, 1.0, 1.0, "Task created")
        return CreateTaskResult(
            task_id=task_id,
            title=title,
            idempotency_key=idempotency_key,
        )

    try:
        result = await execute_with_retries(
            CREATE_TASK_ACTION,
            _attempt,
            config=config,
            idempotency_key=idempotency_key,
        )
    except ActionFailedError:
        if ctx is not None:
            await _log_error(ctx, "create_task failed after retries")
        raise

    store.put(CREATE_TASK_ACTION, idempotency_key, result.model_dump(mode="json"))
    return result
