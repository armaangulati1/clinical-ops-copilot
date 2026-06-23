"""Pydantic models for clinic-ops MCP tool inputs and outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EmailDraft(BaseModel):
    """Draft email (not sent)."""

    to: str = Field(min_length=3)
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    draft_id: str = Field(min_length=1)


class SendEmailResult(BaseModel):
    """Result of a mocked email send."""

    message_id: str = Field(min_length=1)
    to: str = Field(min_length=3)
    subject: str
    idempotency_key: str
    sent_at: datetime


class ScheduleFollowupResult(BaseModel):
    """Result of a mocked follow-up scheduling action."""

    followup_id: str = Field(min_length=1)
    patient_id: str
    when: datetime
    note: str
    idempotency_key: str


class CreateTaskResult(BaseModel):
    """Result of a mocked task/ticket creation."""

    task_id: str = Field(min_length=1)
    title: str
    idempotency_key: str


class ActionFailure(BaseModel):
    """Structured failure after retries are exhausted or a non-retryable error."""

    code: Literal["retries_exhausted", "timeout", "invalid_request"]
    message: str
    action: str
    idempotency_key: str | None = None
    attempts: int = 0
