"""CreateTask — register a new CREATED task with no workflow run (PHASE_4_PLAN CP7).

A thin application service: it builds a :class:`Task` (whose ``__post_init__`` enforces
the title invariant) and persists it in one unit of work. No WorkflowRun is created and
the graph is never invoked — running the task is a separate ``ant run`` command.
"""

from __future__ import annotations

from ant_orchestrator.application.services.workflow_support import UnitOfWorkFactory
from ant_orchestrator.core.domain.entities import Task
from ant_orchestrator.core.domain.enums import TaskPriority, TaskSource, TaskStatus
from ant_orchestrator.core.domain.value_objects import TaskId
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator


class CreateTask:
    """Application use case: create exactly one CREATED task from a title and priority."""

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    def create(self, *, title: str, priority: TaskPriority = TaskPriority.NORMAL) -> Task:
        """Persist a new CREATED task; the title invariant is enforced by ``Task``."""
        now = self._clock.now()
        task = Task(
            id=TaskId(self._ids.new_id()),
            title=title,
            status=TaskStatus.CREATED,
            source=TaskSource.CLI,
            priority=priority,
            created_at=now,
            updated_at=now,
        )
        with self._uow_factory() as uow:
            uow.tasks.add(task)
        return task
