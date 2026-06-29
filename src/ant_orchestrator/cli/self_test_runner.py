"""Self-test orchestration + temporary workspace lifecycle (Phase 8 CP6).

Creates a temporary isolated Nest, runs the deterministic verification scenario
inside an active no-network guard, collects every check, then cleans up the
temporary workspace (unless ``keep_workspace`` is requested). The current project's
``.ant/`` is never read or mutated.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

from ant_orchestrator.cli.composition import build_services
from ant_orchestrator.cli.composition_self_test import (
    SelfTestComposition,
    build_self_test_services,
)
from ant_orchestrator.cli.cp5_doctor_checks import (
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    CheckResult,
)
from ant_orchestrator.cli.network_guard import NetworkGuard
from ant_orchestrator.cli.self_test_checks import (
    audit_checks,
    checkpoint_checks,
    database_checks,
    runtime_checks,
    security_scan_checks,
)
from ant_orchestrator.cli.self_test_scenario import (
    stub_isolation_check,
    workflow_and_result_checks,
)
from ant_orchestrator.cli.self_test_view import SelfTestReport
from ant_orchestrator.workspace.layout import ANT_DIRNAME, ARTIFACTS_DIRNAME

_TEMP_PREFIX = "ant-selftest-"


class SelfTestRunner:
    """Runs the full deterministic self-test and produces a :class:`SelfTestReport`."""

    def __init__(self, *, keep_workspace: bool = False) -> None:
        self._keep = keep_workspace

    def run(self) -> SelfTestReport:
        start = time.monotonic()
        checks: list[CheckResult] = list(runtime_checks())
        workspace: Path | None = None
        cleaned = True
        kept_path: str | None = None
        try:
            workspace = Path(tempfile.mkdtemp(prefix=_TEMP_PREFIX))
            checks.append(CheckResult("workspace.create", STATUS_PASS, "temporary Nest created"))
            checks.extend(self._run_in_workspace(workspace))
        except Exception as exc:  # noqa: BLE001 - normalized into a sanitized check row
            checks.append(
                CheckResult(
                    "workspace.create",
                    STATUS_FAIL,
                    f"self-test aborted: {type(exc).__name__}",
                )
            )
        finally:
            if workspace is not None:
                cleaned, kept_path, cleanup_checks = self._cleanup(workspace)
                checks.extend(cleanup_checks)

        duration_ms = max(0, int((time.monotonic() - start) * 1000))
        return SelfTestReport(
            checks=tuple(checks),
            duration_ms=duration_ms,
            workspace_cleaned=cleaned,
            kept_workspace_path=kept_path,
        )

    # ------------------------------------------------------------------
    def _run_in_workspace(self, workspace: Path) -> list[CheckResult]:
        checks: list[CheckResult] = []
        outcome = build_services().init_nest.init(workspace)
        marker = workspace / ANT_DIRNAME / "workspace.json"
        checks.append(
            CheckResult(
                "workspace.marker",
                STATUS_PASS if marker.exists() else STATUS_FAIL,
                f"marker present ({outcome.value})" if marker.exists() else "marker missing",
            )
        )
        checks.append(_permissions_check(workspace / ANT_DIRNAME))

        composition = build_self_test_services(workspace)
        checks.extend(database_checks(composition.database))

        guard = NetworkGuard()
        with guard:
            checks.extend(workflow_and_result_checks(composition))
        checks.append(
            CheckResult(
                "security.no_network",
                STATUS_PASS if guard.attempts == 0 else STATUS_FAIL,
                "no outbound network attempted"
                if guard.attempts == 0
                else f"{guard.attempts} network attempt(s) blocked",
            )
        )

        checks.extend(checkpoint_checks(composition.checkpoint_db_path))
        checks.extend(
            audit_checks(composition.audit_sink, composition.audit_log_reader, composition.logs_dir)
        )
        checks.extend(security_scan_checks(workspace, _captured_secret_values()))
        checks.append(_boundary_check(workspace, composition))
        checks.append(stub_isolation_check(composition))
        return checks

    def _cleanup(self, workspace: Path) -> tuple[bool, str | None, list[CheckResult]]:
        if self._keep:
            return (
                False,
                str(workspace),
                [
                    CheckResult("cleanup.workspace", STATUS_SKIP, "kept (--keep-workspace)"),
                    CheckResult("cleanup.temporary_files", STATUS_SKIP, "kept (--keep-workspace)"),
                ],
            )
        try:
            shutil.rmtree(workspace, ignore_errors=False)
        except OSError as exc:
            return (
                False,
                None,
                [
                    CheckResult(
                        "cleanup.workspace",
                        STATUS_FAIL,
                        f"could not remove temporary workspace: {type(exc).__name__}",
                    ),
                    CheckResult("cleanup.temporary_files", STATUS_FAIL, "cleanup failed"),
                ],
            )
        gone = not workspace.exists()
        return (
            gone,
            None,
            [
                CheckResult(
                    "cleanup.workspace",
                    STATUS_PASS if gone else STATUS_FAIL,
                    "temporary workspace removed" if gone else "workspace still present",
                ),
                CheckResult(
                    "cleanup.temporary_files",
                    STATUS_PASS if gone else STATUS_FAIL,
                    "no temporary files left behind",
                ),
            ],
        )


def _permissions_check(ant_dir: Path) -> CheckResult:
    try:
        probe = ant_dir / ".selftest_probe"
        probe.write_bytes(b"")
        probe.unlink()
        return CheckResult("workspace.permissions", STATUS_PASS, "workspace is writable")
    except OSError as exc:
        return CheckResult(
            "workspace.permissions", STATUS_FAIL, f"workspace not writable: {type(exc).__name__}"
        )


def _boundary_check(workspace: Path, composition: SelfTestComposition) -> CheckResult:
    """All durable artifacts must live inside the temporary workspace."""
    root = workspace.resolve()
    candidates = [
        composition.database.path,
        composition.checkpoint_db_path,
        composition.logs_dir,
        workspace / ANT_DIRNAME / ARTIFACTS_DIRNAME,
    ]
    for path in candidates:
        try:
            path.resolve().relative_to(root)
        except ValueError:
            return CheckResult(
                "security.workspace_boundary",
                STATUS_FAIL,
                "a durable path escaped the temporary workspace",
            )
    return CheckResult(
        "security.workspace_boundary", STATUS_PASS, "all durable paths within workspace"
    )


def _captured_secret_values() -> tuple[str, ...]:
    """Values of known provider-key environment variables (for the leak scan only).

    The self-test must never write a real API key to disk. We read the configured
    provider-key env values purely to assert they never appear in any workspace
    file — the values are used as scan needles and are never printed or persisted.
    """
    import os

    from ant_orchestrator.config.constants import PROVIDER_KEY_ENV

    values = [os.environ.get(env_name) for env_name in PROVIDER_KEY_ENV.values()]
    return tuple(v for v in values if v)
