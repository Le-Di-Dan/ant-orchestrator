"""Local Docker isolation backend for the Test Ant (PHASE_6_PLAN CP2, ADR-0007).

Implements the CP1 ``TestIsolationPort`` using local Docker as the enforcement boundary.
The backend builds every Docker token deterministically and runs Docker ONLY through the
injected ``ShellAdapter`` port (the bounded subprocess executor) — it never imports
``subprocess`` and never accepts Docker argv/mounts/env from the worker.

Lifecycle: ``docker run --name <unique>`` (no ``--rm``) so timeout/cleanup can force-kill
the whole container via ``docker rm -f`` (idempotent, name-scoped). Backend unavailable or
setup failure fails closed — there is NO host-execution fallback.
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from ant_orchestrator.adapters.container_argv import (
    ContainerRunPlan,
    build_image_inspect_argv,
    build_remove_argv,
    build_run_argv,
    build_version_argv,
)
from ant_orchestrator.application.ports.audit import (
    AuditEvent,
    AuditEventType,
    AuditSink,
    CorrelationId,
)
from ant_orchestrator.application.ports.shell import ShellAdapter, ShellRequest, ShellResult
from ant_orchestrator.application.ports.test_isolation import (
    IsolatedExecutionResult,
    IsolatedExecutionSpec,
    IsolatedRunStatus,
    IsolationCapability,
    IsolationStatus,
    NetworkPolicy,
)
from ant_orchestrator.application.ports.tool_errors import (
    ToolExecutionError,
    ToolNotFoundError,
    ToolPermissionError,
    ToolTimeoutError,
)
from ant_orchestrator.config.constants import (
    TEST_CONTAINER_MEMORY,
    TEST_CONTAINER_NAME_PREFIX,
    TEST_CONTAINER_OUT_MOUNT,
    TEST_CONTAINER_PIDS_LIMIT,
    TEST_CONTAINER_TMPFS_SIZE,
    TEST_CONTAINER_USER,
    TEST_CONTAINER_WORK_MOUNT,
    TEST_EXECUTION_DEFAULT_TIMEOUT_SECONDS,
    TEST_ISOLATION_IMAGE_REF,
)
from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.core.domain.test_failure import TestReasonCode
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator
from ant_orchestrator.security.test_command_profile import TestCommandError, TestCommandResolver

_BACKEND_REF = "container"
_PROBE_TIMEOUT_SECONDS = 30.0
_TOOL_ERRORS = (ToolNotFoundError, ToolTimeoutError, ToolExecutionError, ToolPermissionError)


def _container_env() -> tuple[tuple[str, str], ...]:
    """Sanitized, fixed inner environment (never host values, never secrets)."""
    return (
        ("HOME", TEST_CONTAINER_OUT_MOUNT),
        ("TMPDIR", "/tmp"),
        ("PYTHONDONTWRITEBYTECODE", "1"),
        ("PYTHONUNBUFFERED", "1"),
        ("PYTEST_ADDOPTS", ""),
        ("COVERAGE_FILE", f"{TEST_CONTAINER_OUT_MOUNT}/.coverage"),
    )


class ContainerIsolationBackend:
    """Docker-backed ``TestIsolationPort`` (fail-closed; no host fallback)."""

    __test__ = False  # domain term; not a pytest test class

    def __init__(
        self,
        *,
        shell: ShellAdapter,
        resolver: TestCommandResolver,
        snapshot_root: Path,
        runtime_root: Path,
        audit_sink: AuditSink,
        clock: Clock,
        id_gen: IdGenerator,
        image_ref: str = TEST_ISOLATION_IMAGE_REF,
        timeout_seconds: float = TEST_EXECUTION_DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._shell = shell
        self._resolver = resolver
        self._snapshot_root = snapshot_root.resolve()
        self._runtime_root = runtime_root.resolve()
        self._sink = audit_sink
        self._clock = clock
        self._ids = id_gen
        self._image_ref = image_ref
        self._timeout = timeout_seconds

    # ------------------------------------------------------------------
    # TestIsolationPort
    # ------------------------------------------------------------------

    def capability(self) -> IsolationCapability:
        cid = CorrelationId(self._ids.new_id())
        try:
            version = self._run_shell(build_version_argv(), _PROBE_TIMEOUT_SECONDS)
        except ToolNotFoundError:
            return self._unavailable(cid, "docker_cli_missing")
        except _TOOL_ERRORS:
            return self._unavailable(cid, "daemon_unreachable")
        if version.exit_code != 0:
            return self._unavailable(cid, "daemon_unreachable")
        try:
            inspect = self._run_shell(
                build_image_inspect_argv(self._image_ref), _PROBE_TIMEOUT_SECONDS
            )
        except _TOOL_ERRORS:
            return self._unavailable(cid, "image_inspect_failed")
        if inspect.exit_code != 0:
            return self._unavailable(cid, "image_missing_or_digest_mismatch")
        self._audit(cid, "capability_available", PolicyDecision.ALLOW)
        return IsolationCapability(IsolationStatus.AVAILABLE, backend_ref=_BACKEND_REF)

    def run(self, spec: IsolatedExecutionSpec) -> IsolatedExecutionResult:
        cid = CorrelationId(self._ids.new_id())
        if not self.capability().is_available:
            self._audit(cid, "run_blocked_unavailable", PolicyDecision.DENY)
            return IsolatedExecutionResult(
                IsolatedRunStatus.ISOLATION_UNAVAILABLE, evidence_refs=(str(cid),)
            )
        paths = self._resolve_paths(spec)
        if paths is None:
            self._audit(cid, "snapshot_setup_failed", PolicyDecision.DENY)
            return IsolatedExecutionResult(
                IsolatedRunStatus.ISOLATION_SETUP_FAILED, evidence_refs=(str(cid),)
            )
        try:
            inner_argv = self._resolver.resolve(spec.command_profile_key)
        except TestCommandError:
            self._audit(cid, "command_profile_denied", PolicyDecision.DENY)
            return IsolatedExecutionResult(
                IsolatedRunStatus.ISOLATION_SETUP_FAILED, evidence_refs=(str(cid),)
            )
        return self._launch(spec, paths[0], paths[1], inner_argv, cid)

    # ------------------------------------------------------------------
    # Launch + lifecycle
    # ------------------------------------------------------------------

    def _launch(
        self,
        spec: IsolatedExecutionSpec,
        snapshot_host: Path,
        out_host: Path,
        inner_argv: tuple[str, ...],
        cid: CorrelationId,
    ) -> IsolatedExecutionResult:
        name = self._container_name(spec)
        plan = ContainerRunPlan(
            name=name,
            image_ref=self._image_ref,
            snapshot_host=str(snapshot_host),
            out_host=str(out_host),
            inner_argv=inner_argv,
            user=TEST_CONTAINER_USER,
            pids_limit=TEST_CONTAINER_PIDS_LIMIT,
            memory=TEST_CONTAINER_MEMORY,
            tmpfs_size=TEST_CONTAINER_TMPFS_SIZE,
            work_mount=TEST_CONTAINER_WORK_MOUNT,
            out_mount=TEST_CONTAINER_OUT_MOUNT,
            network_disabled=spec.network_policy is NetworkPolicy.DISABLED,
            env=_container_env(),
        )
        status = IsolatedRunStatus.COMPLETED
        exit_code: int | None = None
        duration_ms = 0
        try:
            result = self._run_shell(build_run_argv(plan), self._timeout)
            exit_code = result.exit_code
            duration_ms = int(result.duration_seconds * 1000)
        except ToolTimeoutError:
            status = IsolatedRunStatus.TIMEOUT
            duration_ms = int(self._timeout * 1000)
        except ToolNotFoundError:
            status = IsolatedRunStatus.ISOLATION_UNAVAILABLE
        except (ToolExecutionError, ToolPermissionError):
            status = IsolatedRunStatus.LAUNCH_FAILED
        finally:
            self._force_remove(name)
        self._audit(cid, f"run_{status.value}", _decision_for(status), {"container": name})
        return IsolatedExecutionResult(
            status=status, exit_code=exit_code, duration_ms=duration_ms, evidence_refs=(str(cid),)
        )

    def _force_remove(self, name: str) -> None:
        """Force-kill + remove the container; idempotent (ignores already-gone)."""
        try:
            self._run_shell(build_remove_argv(name), _PROBE_TIMEOUT_SECONDS)
        except _TOOL_ERRORS:
            pass

    def _resolve_paths(self, spec: IsolatedExecutionSpec) -> tuple[Path, Path] | None:
        snapshot = (self._snapshot_root / spec.snapshot_ref).resolve()
        if not self._within(snapshot, self._snapshot_root) or not snapshot.is_dir():
            return None
        out = (self._runtime_root / spec.runtime_output_ref).resolve()
        if not self._within(out, self._runtime_root):
            return None
        try:
            out.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        return snapshot, out

    @staticmethod
    def _within(path: Path, root: Path) -> bool:
        return path == root or root in path.parents

    def _container_name(self, spec: IsolatedExecutionSpec) -> str:
        parts = (
            spec.snapshot_ref,
            spec.runtime_output_ref,
            spec.command_profile_key,
            self._ids.new_id(),
        )
        digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
        return f"{TEST_CONTAINER_NAME_PREFIX}{digest}"

    def _run_shell(self, argv: tuple[str, ...], timeout: float) -> ShellResult:
        return asyncio.run(self._shell.run(ShellRequest(argv=argv, timeout_seconds=timeout)))

    # ------------------------------------------------------------------
    # Audit (sanitized — bounded strings only)
    # ------------------------------------------------------------------

    def _unavailable(self, cid: CorrelationId, detail: str) -> IsolationCapability:
        self._audit(cid, f"capability_unavailable_{detail}", PolicyDecision.DENY)
        return IsolationCapability(
            IsolationStatus.UNAVAILABLE,
            backend_ref=_BACKEND_REF,
            reason_code=TestReasonCode.EXECUTION_ISOLATION_UNAVAILABLE,
        )

    def _audit(
        self,
        cid: CorrelationId,
        event: str,
        decision: PolicyDecision | None,
        extra: dict[str, str] | None = None,
    ) -> None:
        detail = {"isolation_event": event, "backend": _BACKEND_REF}
        if extra:
            detail.update(extra)
        self._sink.write(
            AuditEvent(
                event_type=AuditEventType.EXECUTION,
                correlation_id=cid,
                created_at=self._clock.now(),
                detail=detail,
                decision=decision,
            )
        )


def _decision_for(status: IsolatedRunStatus) -> PolicyDecision:
    return PolicyDecision.ALLOW if status is IsolatedRunStatus.COMPLETED else PolicyDecision.DENY
