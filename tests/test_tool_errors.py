"""Unit tests for the tool error taxonomy and invocation metadata (CP5)."""

from __future__ import annotations

import inspect

import pytest

from ant_orchestrator.application.ports.tool_common import ToolInvocationMetadata, ToolKind
from ant_orchestrator.application.ports.tool_errors import (
    ToolAdapterError,
    ToolErrorCode,
    ToolExecutionError,
    ToolInvalidRequestError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolTimeoutError,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.errors import AntError

_EXPECTED = [
    (ToolInvalidRequestError, ToolErrorCode.INVALID_REQUEST, False),
    (ToolNotFoundError, ToolErrorCode.NOT_FOUND, False),
    (ToolPermissionError, ToolErrorCode.PERMISSION, False),
    (ToolTimeoutError, ToolErrorCode.TIMEOUT, True),
    (ToolExecutionError, ToolErrorCode.EXECUTION, False),
]
_ALL_CLASSES = [cls for cls, _, _ in _EXPECTED] + [ToolAdapterError]

# Sensitive values that must never be storable in or rendered by a tool error.
_SENTINELS = ("SECRET_SENTINEL_123", "COMMAND_SENTINEL_456", "OUTPUT_SENTINEL_789")
_BANNED_ATTRS = (
    "message",
    "raw_message",
    "command",
    "argv",
    "cwd",
    "output",
    "content",
    "stdout",
    "stderr",
    "diff",
    "cause",
    "original_exception",
)


@pytest.mark.parametrize(("error_cls", "code", "retryable"), _EXPECTED)
def test_error_code_and_default_retryable(
    error_cls: type[ToolAdapterError], code: ToolErrorCode, retryable: bool
) -> None:
    error = error_cls(tool="shell", operation="run")
    assert isinstance(error, AntError)
    assert error.code is code
    assert error.retryable is retryable


def test_execution_error_retryable_can_be_overridden() -> None:
    assert ToolExecutionError(retryable=True).retryable is True


def test_constructor_accepts_only_sanitized_kwargs() -> None:
    params = set(inspect.signature(ToolAdapterError.__init__).parameters) - {"self"}
    assert params <= {"tool", "operation", "retryable"}


@pytest.mark.parametrize("error_cls", _ALL_CLASSES)
def test_str_and_repr_are_sanitized(error_cls: type[ToolAdapterError]) -> None:
    error = error_cls(tool="shell", operation="run", retryable=True)
    rendered = str(error) + repr(error)
    # Only the stable code + sanitized identity is exposed.
    assert error.code.value in rendered
    assert "shell" in rendered
    assert "run" in rendered
    # No sensitive payload can appear (none is accepted in the first place).
    for sentinel in _SENTINELS:
        assert sentinel not in rendered


@pytest.mark.parametrize("error_cls", _ALL_CLASSES)
def test_no_sensitive_public_state(error_cls: type[ToolAdapterError]) -> None:
    error = error_cls(tool="shell", operation="run")
    # Instance state is only the sanitized identity fields.
    assert set(vars(error)) == {"tool", "operation", "retryable"}
    for attr in _BANNED_ATTRS:
        assert not hasattr(error, attr)
    # Exception args carry only the sanitized summary, no raw data.
    for sentinel in _SENTINELS:
        assert all(sentinel not in str(arg) for arg in error.args)


def test_invocation_metadata_requires_operation() -> None:
    with pytest.raises(InvariantViolation):
        ToolInvocationMetadata(tool=ToolKind.SHELL, operation="")


def test_invocation_metadata_is_neutral() -> None:
    meta = ToolInvocationMetadata(tool=ToolKind.GIT, operation="status")
    assert meta.tool is ToolKind.GIT
    assert meta.operation == "status"
