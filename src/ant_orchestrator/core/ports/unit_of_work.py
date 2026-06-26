"""Unit-of-Work port: atomic multi-repository transactions (PHASE_4_PLAN C.13).

A unit of work groups several repository mutations into a single transaction so
that a partial failure rolls *everything* back (no half-written status-transition
log). Repositories obtained from a unit of work never commit independently; the
unit of work owns the connection/transaction lifecycle.

This port is infra-free: the concrete ``SqliteUnitOfWork`` lives in ``persistence``.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol

from ant_orchestrator.core.ports.repositories import (
    ApprovalRepository,
    ExecutionAttemptRepository,
    ResumeOperationRepository,
    StatusTransitionRepository,
    TaskRepository,
    WorkflowRunRepository,
)


class UnitOfWorkRepositories(Protocol):
    """The repositories bound to a single open transaction."""

    @property
    def tasks(self) -> TaskRepository: ...
    @property
    def approvals(self) -> ApprovalRepository: ...
    @property
    def workflow_runs(self) -> WorkflowRunRepository: ...
    @property
    def transitions(self) -> StatusTransitionRepository: ...
    @property
    def execution_attempts(self) -> ExecutionAttemptRepository: ...
    @property
    def resume_operations(self) -> ResumeOperationRepository: ...


class UnitOfWork(Protocol):
    """A context manager that commits on clean exit and rolls back on any error."""

    def __enter__(self) -> UnitOfWorkRepositories: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None: ...
