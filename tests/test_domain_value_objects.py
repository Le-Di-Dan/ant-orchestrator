"""Unit tests for domain value objects (CP1)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta, timezone

import pytest

from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import (
    TaskId,
    TokenCount,
    UtcTimestamp,
    WorkerRunId,
)


def test_identifier_rejects_empty() -> None:
    with pytest.raises(InvariantViolation):
        TaskId("")


def test_identifier_str_returns_value() -> None:
    assert str(TaskId("TASK-1")) == "TASK-1"


def test_identifier_equality_same_type() -> None:
    assert TaskId("a") == TaskId("a")


def test_identifier_distinct_types_not_equal() -> None:
    assert TaskId("a") != WorkerRunId("a")


def test_identifier_is_frozen() -> None:
    task_id = TaskId("a")
    with pytest.raises(dataclasses.FrozenInstanceError):
        task_id.value = "b"  # type: ignore[misc]


def test_utc_timestamp_accepts_utc() -> None:
    ts = UtcTimestamp(datetime(2026, 6, 22, tzinfo=UTC))
    assert ts.to_iso().endswith("+00:00")


def test_utc_timestamp_rejects_naive() -> None:
    with pytest.raises(InvariantViolation):
        UtcTimestamp(datetime(2026, 6, 22))


def test_utc_timestamp_rejects_non_utc_offset() -> None:
    plus_seven = timezone(timedelta(hours=7))
    with pytest.raises(InvariantViolation):
        UtcTimestamp(datetime(2026, 6, 22, tzinfo=plus_seven))


def test_from_datetime_normalizes_to_utc() -> None:
    plus_seven = timezone(timedelta(hours=7))
    aware = datetime(2026, 6, 22, 7, 0, 0, tzinfo=plus_seven)
    ts = UtcTimestamp.from_datetime(aware)
    assert ts.value == datetime(2026, 6, 22, 0, 0, 0, tzinfo=UTC)


def test_from_datetime_rejects_naive() -> None:
    with pytest.raises(InvariantViolation):
        UtcTimestamp.from_datetime(datetime(2026, 6, 22))


def test_from_iso_roundtrip() -> None:
    ts = UtcTimestamp(datetime(2026, 6, 22, 12, 30, tzinfo=UTC))
    assert UtcTimestamp.from_iso(ts.to_iso()) == ts


def test_from_iso_rejects_garbage() -> None:
    with pytest.raises(InvariantViolation):
        UtcTimestamp.from_iso("not-a-timestamp")


def test_token_count_accepts_zero() -> None:
    assert TokenCount(0).value == 0


def test_token_count_rejects_negative() -> None:
    with pytest.raises(InvariantViolation):
        TokenCount(-1)
