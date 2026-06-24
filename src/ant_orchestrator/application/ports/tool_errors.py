"""Neutral tool/execution adapter error taxonomy (PHASE_2_PLAN §CP5).

Shared by every tool port (filesystem, shell, test runner, git-read). Errors carry
only sanitized metadata — a stable ``code``, ``retryable`` hint and optional
tool/operation identifiers. They MUST NOT embed raw commands, stdout/stderr, file
or diff contents, secrets or raw underlying exceptions.

Adapter errors signal a failure of the *invocation/boundary*, never an expected
business outcome (a non-zero shell exit, a failing test, a dirty repo and an empty
diff are all valid results, not errors).
"""

from __future__ import annotations

from enum import Enum
from typing import ClassVar

from ant_orchestrator.errors import AntError


class ToolErrorCode(Enum):
    """Stable, neutral tool error codes."""

    UNKNOWN = "tool.unknown"
    INVALID_REQUEST = "tool.invalid_request"
    NOT_FOUND = "tool.not_found"
    PERMISSION = "tool.permission"
    TIMEOUT = "tool.timeout"
    EXECUTION = "tool.execution"


class ToolAdapterError(AntError):
    """Base class for tool/execution boundary failures.

    The constructor accepts only sanitized identity (``tool``/``operation``) and a
    ``retryable`` override — there is deliberately no free-form message parameter,
    so no raw command/output/content/secret can be stored or rendered. Both
    ``str`` and ``repr`` expose only the stable code and sanitized identity.
    """

    code: ClassVar[ToolErrorCode] = ToolErrorCode.UNKNOWN
    default_retryable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        tool: str | None = None,
        operation: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.tool = tool
        self.operation = operation
        self.retryable = self.default_retryable if retryable is None else retryable
        super().__init__(self._summary())

    def _summary(self) -> str:
        return (
            f"{self.code.value}(tool={self.tool}, operation={self.operation}, "
            f"retryable={self.retryable})"
        )

    def __str__(self) -> str:
        return self._summary()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(code={self.code.value!r}, retryable={self.retryable}, "
            f"tool={self.tool!r}, operation={self.operation!r})"
        )


class ToolInvalidRequestError(ToolAdapterError):
    """The tool request was malformed or unsupported."""

    code = ToolErrorCode.INVALID_REQUEST
    default_retryable = False


class ToolNotFoundError(ToolAdapterError):
    """A required target (path, executable, repository) does not exist."""

    code = ToolErrorCode.NOT_FOUND
    default_retryable = False


class ToolPermissionError(ToolAdapterError):
    """The boundary denied the operation."""

    code = ToolErrorCode.PERMISSION
    default_retryable = False


class ToolTimeoutError(ToolAdapterError):
    """The operation exceeded its timeout."""

    code = ToolErrorCode.TIMEOUT
    default_retryable = True


class ToolExecutionError(ToolAdapterError):
    """The tool could not be invoked or failed at the boundary.

    ``default_retryable`` is conservatively ``False``; set ``retryable=True`` only
    when the cause is known to be transient.
    """

    code = ToolErrorCode.EXECUTION
    default_retryable = False
