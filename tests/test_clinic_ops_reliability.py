"""Unit tests for clinic-ops send_email idempotency and chaos resilience."""

from __future__ import annotations

import json
import random

import pytest

from servers.clinic_ops.actions import create_task, schedule_followup, send_email
from servers.clinic_ops.config import ServerConfig
from servers.clinic_ops.errors import ActionFailedError
from servers.clinic_ops.idempotency import InMemoryIdempotencyStore
from servers.clinic_ops.mock_backend import MockBackend
from servers.clinic_ops.schemas import ActionFailure


@pytest.fixture
def fast_config() -> ServerConfig:
    return ServerConfig(
        latency_min_seconds=0.0,
        latency_max_seconds=0.0,
        failure_rate=0.0,
        rng_seed=42,
        mock_timeout_seconds=5.0,
        max_attempts=5,
        backoff_min_seconds=0.01,
        backoff_max_seconds=0.05,
    )


@pytest.fixture
def chaos_config() -> ServerConfig:
    return ServerConfig(
        latency_min_seconds=0.0,
        latency_max_seconds=0.0,
        failure_rate=0.30,
        rng_seed=12345,
        mock_timeout_seconds=5.0,
        max_attempts=8,
        backoff_min_seconds=0.01,
        backoff_max_seconds=0.05,
    )


@pytest.fixture
def store() -> InMemoryIdempotencyStore:
    return InMemoryIdempotencyStore()


@pytest.mark.anyio
async def test_send_email_idempotent_replay(
    fast_config: ServerConfig,
    store: InMemoryIdempotencyStore,
) -> None:
    backend = MockBackend(config=fast_config, rng=random.Random(1))
    first = await send_email(
        "patient@example.com",
        "Prior auth update",
        "Body",
        "key-1",
        store=store,
        backend=backend,
        config=fast_config,
    )
    second = await send_email(
        "patient@example.com",
        "Prior auth update",
        "Body",
        "key-1",
        store=store,
        backend=backend,
        config=fast_config,
    )
    assert first.message_id == second.message_id
    assert backend.counters.sends == 1


@pytest.mark.anyio
async def test_send_email_different_keys_send_separately(
    fast_config: ServerConfig,
    store: InMemoryIdempotencyStore,
) -> None:
    backend = MockBackend(config=fast_config, rng=random.Random(2))
    await send_email(
        "a@example.com",
        "One",
        "Body",
        "key-a",
        store=store,
        backend=backend,
        config=fast_config,
    )
    await send_email(
        "b@example.com",
        "Two",
        "Body",
        "key-b",
        store=store,
        backend=backend,
        config=fast_config,
    )
    assert backend.counters.sends == 2


@pytest.mark.anyio
async def test_chaos_send_email_recovers_without_double_send(
    chaos_config: ServerConfig,
    store: InMemoryIdempotencyStore,
) -> None:
    backend = MockBackend(config=chaos_config, rng=random.Random(chaos_config.rng_seed))
    keys = [f"chaos-send-{index}" for index in range(40)]

    for key in keys:
        await send_email(
            "patient@example.com",
            "Subject",
            "Body",
            key,
            store=store,
            backend=backend,
            config=chaos_config,
        )
        replay = await send_email(
            "patient@example.com",
            "Subject",
            "Body",
            key,
            store=store,
            backend=backend,
            config=chaos_config,
        )
        assert replay.idempotency_key == key

    assert backend.counters.sends == len(keys)


@pytest.mark.anyio
async def test_chaos_all_action_tools_complete_once_per_key(
    chaos_config: ServerConfig,
    store: InMemoryIdempotencyStore,
) -> None:
    backend = MockBackend(config=chaos_config, rng=random.Random(999))
    from datetime import UTC, datetime

    when = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)

    for index in range(20):
        key = f"bundle-{index}"
        await send_email(
            "p@example.com",
            "S",
            "B",
            f"send-{key}",
            store=store,
            backend=backend,
            config=chaos_config,
        )
        await schedule_followup(
            "patient-001",
            when,
            "note",
            f"sched-{key}",
            store=store,
            backend=backend,
            config=chaos_config,
        )
        await create_task(
            "Task",
            "Details",
            f"task-{key}",
            store=store,
            backend=backend,
            config=chaos_config,
        )

    assert backend.counters.sends == 20
    assert backend.counters.schedules == 20
    assert backend.counters.tasks == 20


@pytest.mark.anyio
async def test_timeout_fails_with_structured_error(
    store: InMemoryIdempotencyStore,
) -> None:
    config = ServerConfig(
        latency_min_seconds=1.0,
        latency_max_seconds=1.0,
        failure_rate=0.0,
        mock_timeout_seconds=0.05,
        max_attempts=1,
        backoff_min_seconds=0.01,
        backoff_max_seconds=0.02,
    )
    backend = MockBackend(config=config, rng=random.Random(0))

    with pytest.raises(ActionFailedError) as exc_info:
        await send_email(
            "patient@example.com",
            "Subject",
            "Body",
            "timeout-key",
            store=store,
            backend=backend,
            config=config,
        )

    failure = exc_info.value.failure
    assert failure.code == "timeout"
    ActionFailure.model_validate(failure.model_dump(mode="json"))
    assert "timeout" in failure.message.lower()


def test_action_failure_serializes_to_json() -> None:
    failure = ActionFailure(
        code="timeout",
        message="timed out",
        action="send_email",
        idempotency_key="k1",
        attempts=1,
    )
    parsed = ActionFailure.model_validate(json.loads(failure.model_dump_json()))
    assert parsed.code == "timeout"
