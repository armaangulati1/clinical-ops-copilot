"""Retry and timeout helpers for clinic-ops actions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from servers.clinic_ops.config import ServerConfig
from servers.clinic_ops.errors import MockTimeoutError, TransientMockError
from servers.clinic_ops.schemas import ActionFailure

T = TypeVar("T")


async def execute_with_retries(
    action_name: str,
    operation: Callable[[], Awaitable[T]],
    *,
    config: ServerConfig,
    idempotency_key: str | None = None,
) -> T:
    """Run an async operation with exponential backoff on transient errors."""
    attempts = 0
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(config.max_attempts),
            wait=wait_exponential(
                multiplier=1,
                min=config.backoff_min_seconds,
                max=config.backoff_max_seconds,
            ),
            retry=retry_if_exception_type(TransientMockError),
            reraise=True,
        ):
            with attempt:
                attempts = attempt.retry_state.attempt_number
                return await operation()
    except TransientMockError as exc:
        from servers.clinic_ops.errors import ActionFailedError

        failure = ActionFailure(
            code="retries_exhausted",
            message=str(exc),
            action=action_name,
            idempotency_key=idempotency_key,
            attempts=attempts or config.max_attempts,
        )
        raise ActionFailedError(failure) from exc
    except MockTimeoutError as exc:
        from servers.clinic_ops.errors import ActionFailedError

        failure = ActionFailure(
            code="timeout",
            message=str(exc),
            action=action_name,
            idempotency_key=idempotency_key,
            attempts=attempts or 1,
        )
        raise ActionFailedError(failure) from exc

    msg = f"unreachable after retries for action {action_name}"
    raise RuntimeError(msg)
