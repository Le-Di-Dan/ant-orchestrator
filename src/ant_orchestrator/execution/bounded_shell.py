"""Bounded subprocess executor — the ONLY module allowed to import subprocess (CP3).

Implements the Phase 2 ``ShellAdapter`` protocol with full enforcement:
command policy, CWD validation, trusted executable resolution, output byte
limiting, secret redaction, timeout with process-group kill, and audit events.

``shell=True`` is never used. Raw argv is never persisted or raised.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO, Any, Final

from ant_orchestrator.application.ports.audit import (
    AuditEvent,
    AuditEventType,
    AuditSink,
    CorrelationId,
)
from ant_orchestrator.application.ports.shell import ShellRequest, ShellResult
from ant_orchestrator.application.ports.tool_common import (
    ToolInvocationMetadata,
    ToolKind,
)
from ant_orchestrator.application.ports.tool_errors import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolTimeoutError,
)
from ant_orchestrator.config.constants import (
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    MAX_COMMAND_TIMEOUT_SECONDS,
    PROCESS_KILL_GRACE_SECONDS,
)
from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator
from ant_orchestrator.execution.output_limit import (
    OutputLimit,
    OutputLimiter,
    TruncatedOutput,
)
from ant_orchestrator.security.command_policy import CommandPolicy
from ant_orchestrator.security.path_policy import PathPolicy
from ant_orchestrator.security.redaction.redactor import Redactor

_POSIX: Final = sys.platform != "win32"
_TOOL: Final = "shell"
_OP: Final = "run"
_EMPTY: Final = TruncatedOutput("", False, 0)


class BoundedShellConfig:
    """Injected configuration for the bounded executor."""

    __slots__ = (
        "workspace_root",
        "trusted_executables",
        "output_limit",
        "default_timeout",
        "max_timeout",
    )

    def __init__(
        self,
        workspace_root: Path,
        trusted_executables: dict[str, Path],
        output_limit: OutputLimit,
        default_timeout: float = DEFAULT_COMMAND_TIMEOUT_SECONDS,
        max_timeout: float = MAX_COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        self.workspace_root = workspace_root
        self.trusted_executables = trusted_executables
        self.output_limit = output_limit
        self.default_timeout = default_timeout
        self.max_timeout = max_timeout


class SubprocessShellAdapter:
    """Bounded ``ShellAdapter`` with policy, timeout, redaction and audit."""

    def __init__(
        self,
        config: BoundedShellConfig,
        command_policy: CommandPolicy,
        cwd_policy: PathPolicy,
        redactor: Redactor,
        audit_sink: AuditSink,
        clock: Clock,
        id_gen: IdGenerator,
    ) -> None:
        self._cfg = config
        self._cmd_policy = command_policy
        self._cwd_policy = cwd_policy
        self._limiter = OutputLimiter(config.output_limit, redactor)
        self._audit = audit_sink
        self._clock = clock
        self._ids = id_gen
        self._ws = config.workspace_root.resolve()

    async def run(self, request: ShellRequest) -> ShellResult:
        return await asyncio.to_thread(self._run_sync, request)

    def _run_sync(self, req: ShellRequest) -> ShellResult:
        cid = CorrelationId(self._ids.new_id())
        cmd_d = self._cmd_policy.check(req.argv)
        if cmd_d.decision is PolicyDecision.DENY:
            self._audit_deny(cid, "command_denied", req)
            raise ToolPermissionError(tool=_TOOL, operation=_OP)
        cwd = self._resolve_cwd(req.cwd, cid, req)
        exe = self._resolve_executable(req.argv[0], cid)
        timeout = self._effective_timeout(req.timeout_seconds)
        self._audit_pre(cid, req)
        return self._execute(exe, req.argv[1:], cwd, timeout, cid)

    # ------------------------------------------------------------------
    # CWD / executable resolution
    # ------------------------------------------------------------------

    def _resolve_cwd(self, raw: str | None, cid: CorrelationId, req: ShellRequest) -> Path:
        if raw is None:
            return self._ws
        d = self._cwd_policy.check_directory(raw)
        if d.decision is PolicyDecision.DENY:
            self._audit_deny(cid, "cwd_denied", req)
            raise ToolPermissionError(tool=_TOOL, operation=_OP)
        assert d.resolved is not None
        return d.resolved

    def _resolve_executable(self, name: str, cid: CorrelationId) -> Path:
        if name in self._cfg.trusted_executables:
            path = self._cfg.trusted_executables[name]
            if path.is_file():
                return path
        elif "/" in name or "\\" in name:
            p = Path(name)
            if p.is_absolute() and p.is_file():
                return p.resolve()
        self._audit_event(
            cid,
            AuditEventType.COMMAND_DECISION,
            PolicyDecision.DENY,
            {"reason": "executable_not_found"},
        )
        raise ToolNotFoundError(tool=_TOOL, operation="resolve")

    def _effective_timeout(self, requested: float | None) -> float:
        if requested is not None and requested > 0:
            return min(requested, self._cfg.max_timeout)
        return self._cfg.default_timeout

    # ------------------------------------------------------------------
    # Process spawn + drain
    # ------------------------------------------------------------------

    def _execute(
        self,
        exe: Path,
        args: tuple[str, ...],
        cwd: Path,
        timeout: float,
        cid: CorrelationId,
    ) -> ShellResult:
        argv = [str(exe), *args]
        start = time.monotonic()
        proc = self._spawn(argv, cwd)
        timed_out = False
        try:
            so, se = self._drain(proc, timeout)
            remaining = max(timeout - (time.monotonic() - start), 0.1)
            exit_code = proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(proc)
            so, se = _drain_leftover(proc, self._limiter)
            exit_code = proc.poll() or -1
        duration = time.monotonic() - start
        self._audit_post(cid, exit_code, duration, so, se, timed_out)
        if timed_out:
            raise ToolTimeoutError(tool=_TOOL, operation=_OP)
        return ShellResult(
            exit_code=exit_code,
            stdout=so.text,
            stderr=se.text,
            duration_seconds=duration,
            invocation=ToolInvocationMetadata(ToolKind.SHELL, _OP),
        )

    @staticmethod
    def _spawn(argv: list[str], cwd: Path) -> subprocess.Popen[bytes]:
        try:
            if _POSIX:
                return subprocess.Popen(  # noqa: S603
                    argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    stdin=subprocess.DEVNULL,
                    cwd=str(cwd),
                    start_new_session=True,
                )
            return subprocess.Popen(  # noqa: S603
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                cwd=str(cwd),
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
        except OSError:
            raise ToolExecutionError(tool=_TOOL, operation=_OP) from None

    def _drain(
        self,
        proc: subprocess.Popen[bytes],
        timeout: float,
    ) -> tuple[TruncatedOutput, TruncatedOutput]:
        assert proc.stdout is not None and proc.stderr is not None
        results: list[TruncatedOutput] = [_EMPTY, _EMPTY]

        def _read(idx: int, pipe: IO[bytes]) -> None:
            try:
                results[idx] = self._limiter.drain_and_process(pipe)  # type: ignore[arg-type]
            except (OSError, ValueError):
                pass

        threads = [
            threading.Thread(target=_read, args=(0, proc.stdout), daemon=True),
            threading.Thread(target=_read, args=(1, proc.stderr), daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=timeout + 2)
        return results[0], results[1]

    # ------------------------------------------------------------------
    # Audit helpers (sanitized — no raw argv/output)
    # ------------------------------------------------------------------

    def _audit_event(
        self,
        cid: CorrelationId,
        etype: AuditEventType,
        decision: PolicyDecision | None,
        detail: dict[str, str],
    ) -> None:
        self._audit.write(
            AuditEvent(
                event_type=etype,
                correlation_id=cid,
                created_at=self._clock.now(),
                detail=detail,
                decision=decision,
            )
        )

    def _audit_deny(
        self,
        cid: CorrelationId,
        reason: str,
        req: ShellRequest,
    ) -> None:
        self._audit_event(
            cid,
            AuditEventType.COMMAND_DECISION,
            PolicyDecision.DENY,
            {"reason": reason, "arg_count": str(len(req.argv))},
        )

    def _audit_pre(self, cid: CorrelationId, req: ShellRequest) -> None:
        self._audit_event(
            cid,
            AuditEventType.COMMAND_DECISION,
            PolicyDecision.ALLOW,
            {"arg_count": str(len(req.argv))},
        )

    def _audit_post(
        self,
        cid: CorrelationId,
        ec: int,
        dur: float,
        so: TruncatedOutput,
        se: TruncatedOutput,
        to: bool,
    ) -> None:
        d = {
            "exit_code": str(ec),
            "duration_s": f"{dur:.3f}",
            "stdout_bytes": str(so.original_bytes),
            "stderr_bytes": str(se.original_bytes),
            "stdout_truncated": str(so.truncated),
            "stderr_truncated": str(se.truncated),
            "timed_out": str(to),
        }
        if so.truncated or se.truncated:
            self._audit_event(cid, AuditEventType.OUTPUT_TRUNCATED, None, d)
        self._audit_event(cid, AuditEventType.EXECUTION, None, d)


# ======================================================================
# Module-private helpers
# ======================================================================


def _kill(proc: subprocess.Popen[Any]) -> None:
    """Terminate then force-kill process/group with bounded grace period."""
    import os
    import signal as sig

    try:
        if _POSIX:
            os.killpg(os.getpgid(proc.pid), sig.SIGTERM)  # type: ignore[attr-defined]
        else:
            proc.terminate()
    except (OSError, ProcessLookupError):
        pass
    try:
        proc.wait(timeout=PROCESS_KILL_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            if _POSIX:
                os.killpg(os.getpgid(proc.pid), sig.SIGKILL)  # type: ignore[attr-defined]
            else:
                proc.kill()
        except (OSError, ProcessLookupError):
            pass
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def _drain_leftover(
    proc: subprocess.Popen[Any],
    limiter: OutputLimiter,
) -> tuple[TruncatedOutput, TruncatedOutput]:
    so = proc.stdout.read() if proc.stdout else b""
    se = proc.stderr.read() if proc.stderr else b""
    return limiter.process_bytes(so), limiter.process_bytes(se)
