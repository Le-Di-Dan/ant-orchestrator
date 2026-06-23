"""Unit tests for domain enumerations (CP1)."""

from __future__ import annotations

import pytest

from ant_orchestrator.core.domain.enums import (
    ApprovalStatus,
    TaskStatus,
    WorkerRunStatus,
)
from ant_orchestrator.core.domain.errors import InvalidStatusValue


def test_parse_returns_member() -> None:
    assert TaskStatus.parse("created") is TaskStatus.CREATED


def test_parse_unknown_raises() -> None:
    with pytest.raises(InvalidStatusValue):
        TaskStatus.parse("does_not_exist")


def test_str_is_canonical_value() -> None:
    assert str(TaskStatus.WAITING_FOR_APPROVAL) == "waiting_for_approval"


def test_all_values_are_strings() -> None:
    for member in TaskStatus:
        assert isinstance(member.value, str)


def test_task_terminal_statuses() -> None:
    terminal = {s for s in TaskStatus if s.is_terminal}
    assert terminal == {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
        TaskStatus.REJECTED,
    }


def test_waiting_for_approval_is_not_terminal() -> None:
    assert not TaskStatus.WAITING_FOR_APPROVAL.is_terminal


def test_approval_terminal_statuses() -> None:
    assert ApprovalStatus.APPROVED.is_terminal
    assert ApprovalStatus.REJECTED.is_terminal
    assert not ApprovalStatus.PENDING.is_terminal


def test_worker_run_terminal_statuses() -> None:
    terminal = {s for s in WorkerRunStatus if s.is_terminal}
    assert terminal == {
        WorkerRunStatus.SUCCEEDED,
        WorkerRunStatus.FAILED,
        WorkerRunStatus.CANCELLED,
    }
