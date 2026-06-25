"""Bounded filesystem adapter — read/write with path policy enforcement (CP4).

Implements the Phase 2 ``FileSystemAdapter`` protocol. Every operation goes
through ``PathPolicy`` for scope, traversal and symlink-escape checks. Reads
are byte-limited, binary-detected, and secret-redacted before returning.
Writes are scope-checked and revalidated; content is written verbatim (no
redaction of user data). No subprocess, no concrete audit adapter import.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Final

from ant_orchestrator.application.ports.audit import (
    AuditEvent,
    AuditEventType,
    AuditSink,
    CorrelationId,
)
from ant_orchestrator.application.ports.filesystem import (
    ContentRedaction,
    FileReadRequest,
    FileReadResult,
    FileWriteRequest,
    FileWriteResult,
)
from ant_orchestrator.application.ports.tool_common import ToolInvocationMetadata, ToolKind
from ant_orchestrator.application.ports.tool_errors import (
    ToolExecutionError,
    ToolInvalidRequestError,
    ToolNotFoundError,
    ToolPermissionError,
)
from ant_orchestrator.config.constants import DEFAULT_MAX_READ_BYTES
from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator
from ant_orchestrator.security.path_policy import DenyReason, PathAccess, PathPolicy
from ant_orchestrator.security.redaction.redactor import Redactor

_TOOL: Final = "filesystem"
_NOT_FOUND_REASONS: Final = frozenset({DenyReason.NOT_FOUND})
_INVALID_REASONS: Final = frozenset(
    {DenyReason.NOT_A_FILE, DenyReason.NOT_A_DIRECTORY, DenyReason.INVALID_PATH}
)


class BoundedFsConfig:
    """Injected configuration for the bounded filesystem adapter."""

    __slots__ = ("workspace_root", "max_read_bytes")

    def __init__(
        self,
        workspace_root: Path,
        max_read_bytes: int = DEFAULT_MAX_READ_BYTES,
    ) -> None:
        self.workspace_root = workspace_root
        self.max_read_bytes = max_read_bytes


class BoundedFileSystemAdapter:
    """Bounded ``FileSystemAdapter`` with path policy, redaction, and audit."""

    def __init__(
        self,
        config: BoundedFsConfig,
        path_policy: PathPolicy,
        redactor: Redactor,
        audit_sink: AuditSink,
        clock: Clock,
        id_gen: IdGenerator,
    ) -> None:
        self._cfg = config
        self._policy = path_policy
        self._redactor = redactor
        self._audit = audit_sink
        self._clock = clock
        self._ids = id_gen

    async def read_text(self, request: FileReadRequest) -> FileReadResult:
        return await asyncio.to_thread(self._read_sync, request)

    async def write_text(self, request: FileWriteRequest) -> FileWriteResult:
        return await asyncio.to_thread(self._write_sync, request)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def _read_sync(self, req: FileReadRequest) -> FileReadResult:
        cid = CorrelationId(self._ids.new_id())
        decision = self._policy.check(req.path, PathAccess.READ)
        if decision.decision is PolicyDecision.DENY:
            self._audit_deny(cid, "read_text", req.path, decision.reason)
            _raise_for_deny(decision.reason, "read_text")
        assert decision.resolved is not None
        resolved = decision.resolved

        self._audit_allow(cid, "read_text")

        try:
            size = resolved.stat().st_size
        except OSError:
            raise ToolExecutionError(tool=_TOOL, operation="read_text") from None
        if size > self._cfg.max_read_bytes:
            raise ToolInvalidRequestError(
                tool=_TOOL, operation="read_text", detail_code="oversized"
            )

        try:
            with resolved.open("rb") as f:
                raw = f.read(self._cfg.max_read_bytes + 1)
        except OSError:
            raise ToolExecutionError(tool=_TOOL, operation="read_text") from None
        if len(raw) > self._cfg.max_read_bytes:
            raise ToolInvalidRequestError(
                tool=_TOOL, operation="read_text", detail_code="oversized"
            )

        if b"\x00" in raw:
            raise ToolInvalidRequestError(
                tool=_TOOL, operation="read_text", detail_code="binary_content"
            )
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise ToolInvalidRequestError(
                tool=_TOOL, operation="read_text", detail_code="invalid_encoding"
            ) from None

        redacted = self._redactor.redact(text)
        redactions = tuple(
            ContentRedaction(pattern=m.pattern.value, count=m.count) for m in redacted.marks
        )
        return FileReadResult(
            path=req.path,
            content=redacted.text,
            invocation=ToolInvocationMetadata(ToolKind.FILESYSTEM, "read_text"),
            redactions=redactions,
        )

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def _write_sync(self, req: FileWriteRequest) -> FileWriteResult:
        cid = CorrelationId(self._ids.new_id())
        decision = self._policy.check(req.path, PathAccess.WRITE)
        if decision.decision is PolicyDecision.DENY:
            self._audit_deny(cid, "write_text", req.path, decision.reason)
            _raise_for_deny(decision.reason, "write_text")
        assert decision.resolved is not None
        resolved = decision.resolved

        self._audit_allow(cid, "write_text")

        recheck = self._policy.check(req.path, PathAccess.WRITE)
        if recheck.decision is PolicyDecision.DENY:
            self._audit_deny(cid, "write_text_revalidate", req.path, recheck.reason)
            _raise_for_deny(recheck.reason, "write_text")
        assert recheck.resolved is not None
        resolved = recheck.resolved

        if resolved.is_file():
            try:
                existing = resolved.read_text(encoding="utf-8")
            except OSError:
                existing = None
            if existing == req.content:
                return FileWriteResult(
                    path=req.path,
                    changed=False,
                    invocation=ToolInvocationMetadata(ToolKind.FILESYSTEM, "write_text"),
                )

        try:
            resolved.write_text(req.content, encoding="utf-8")
        except FileNotFoundError:
            raise ToolNotFoundError(tool=_TOOL, operation="write_text") from None
        except OSError:
            raise ToolExecutionError(tool=_TOOL, operation="write_text") from None

        return FileWriteResult(
            path=req.path,
            changed=True,
            invocation=ToolInvocationMetadata(ToolKind.FILESYSTEM, "write_text"),
        )

    # ------------------------------------------------------------------
    # Audit helpers (no raw content)
    # ------------------------------------------------------------------

    def _audit_deny(
        self,
        cid: CorrelationId,
        op: str,
        path: str,
        reason: DenyReason | None,
    ) -> None:
        self._audit.write(
            AuditEvent(
                event_type=AuditEventType.PATH_DECISION,
                correlation_id=cid,
                created_at=self._clock.now(),
                detail={"operation": op, "reason": reason.value if reason else "unknown"},
                decision=PolicyDecision.DENY,
            )
        )

    def _audit_allow(self, cid: CorrelationId, op: str) -> None:
        self._audit.write(
            AuditEvent(
                event_type=AuditEventType.PATH_DECISION,
                correlation_id=cid,
                created_at=self._clock.now(),
                detail={"operation": op},
                decision=PolicyDecision.ALLOW,
            )
        )


def _raise_for_deny(reason: DenyReason | None, op: str) -> None:
    """Map PathPolicy deny reason to the appropriate tool error."""
    if reason in _NOT_FOUND_REASONS:
        raise ToolNotFoundError(tool=_TOOL, operation=op)
    if reason in _INVALID_REASONS:
        raise ToolInvalidRequestError(tool=_TOOL, operation=op)
    raise ToolPermissionError(tool=_TOOL, operation=op)
