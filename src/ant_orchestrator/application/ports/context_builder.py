"""Context builder port — typed contracts for context selection (CP5).

Defines the consumer model, artifact request/budget DTOs, and error taxonomy
used by callers without depending on implementation in ``context/``.
``ContextBudget`` lives here (not in ``context/``) so that ``ContextBuildRequest``
does not create a reverse dependency from application ports to implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TaskId
from ant_orchestrator.errors import AntError

_MAX_CONSUMER_VALUE_LENGTH: Final = 256


class ConsumerKind(Enum):
    """The role/capability that consumes context."""

    WORKER = "worker"
    CAPABILITY = "capability"
    PLANNER = "planner"
    REVIEWER = "reviewer"
    DETERMINISTIC_TOOL = "deterministic_tool"
    EXECUTION_STAGE = "execution_stage"


@dataclass(frozen=True, slots=True)
class ContextConsumer:
    """Identifies *what* receives context (role/capability), not a worker entity."""

    kind: ConsumerKind
    value: str

    def __post_init__(self) -> None:
        if not self.value or not self.value.strip():
            raise InvariantViolation("ContextConsumer.value must be non-empty")
        if len(self.value) > _MAX_CONSUMER_VALUE_LENGTH:
            raise InvariantViolation(
                f"ContextConsumer.value must be <= {_MAX_CONSUMER_VALUE_LENGTH} characters"
            )


class ArtifactRequirement(Enum):
    """Whether an artifact is mandatory or best-effort."""

    REQUIRED = "required"
    OPTIONAL = "optional"


@dataclass(frozen=True, slots=True)
class ArtifactRequest:
    """An explicit request for a specific artifact by path."""

    path: str
    requirement: ArtifactRequirement

    def __post_init__(self) -> None:
        if not self.path:
            raise InvariantViolation("ArtifactRequest.path must be non-empty")


@dataclass(frozen=True, slots=True)
class ContextBudget:
    """Deterministic budget constraints for context selection."""

    max_input_tokens: int
    max_files: int
    max_file_tokens: int
    allow_full_file: bool = False

    def __post_init__(self) -> None:
        if self.max_input_tokens <= 0:
            raise InvariantViolation("ContextBudget.max_input_tokens must be > 0")
        if self.max_files <= 0:
            raise InvariantViolation("ContextBudget.max_files must be > 0")
        if self.max_file_tokens <= 0:
            raise InvariantViolation("ContextBudget.max_file_tokens must be > 0")
        if self.max_file_tokens > self.max_input_tokens:
            raise InvariantViolation("ContextBudget.max_file_tokens must be <= max_input_tokens")


@dataclass(frozen=True, slots=True)
class ContextBuildRequest:
    """Everything a ContextBuilder needs to build a context package."""

    task_id: TaskId
    consumer: ContextConsumer
    requests: tuple[ArtifactRequest, ...]
    excluded: tuple[str, ...]
    budget: ContextBudget


class ContextError(AntError):
    """Base class for context-related errors."""


class ContextBudgetExceededError(ContextError):
    """A required artifact exceeds the context budget."""


class ContextScopeViolation(ContextError):
    """An artifact request targets a path outside the allowed scope."""
