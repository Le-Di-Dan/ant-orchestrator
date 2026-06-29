"""Phase 8 CP5 — Doctor workspace and provider health checks.

Separated from cp5_doctor_checks.py to keep each source file under 350 lines.
"""

from __future__ import annotations

import os
from pathlib import Path

from ant_orchestrator.cli.cp5_doctor_checks import (
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    STATUS_WARN,
    CheckResult,
)
from ant_orchestrator.config.constants import (
    CONFIGURE_SUPPORTED_PROVIDERS,
    EXPECTED_DB_SCHEMA_VERSION,
    PROVIDER_KEY_ENV,
)
from ant_orchestrator.config.loader import load_document
from ant_orchestrator.config.resolver import ConfigResolver
from ant_orchestrator.persistence.migrations import SqliteDatabaseInspector
from ant_orchestrator.workspace.discovery import find_nest
from ant_orchestrator.workspace.layout import (
    ANT_DIRNAME,
    CHECKPOINT_DB_FILENAME,
    DATABASE_FILENAME,
    MARKER_FILENAME,
)


def check_workspace(search_root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    root = find_nest(search_root)
    if root is None:
        results.append(
            CheckResult(
                check_id="workspace.found",
                status=STATUS_WARN,
                message=f"No .ant/ workspace found from {search_root}",
                remediation="Run: antctl init  (inside your project directory)",
            )
        )
        return results
    results.append(
        CheckResult(
            check_id="workspace.found",
            status=STATUS_PASS,
            message=f"Workspace at {root}",
        )
    )
    ant_dir = root / ANT_DIRNAME
    marker = ant_dir / MARKER_FILENAME
    results.append(
        CheckResult(
            check_id="workspace.marker",
            status=STATUS_PASS if marker.exists() else STATUS_FAIL,
            message="workspace.json present" if marker.exists() else "workspace.json missing",
            remediation=None if marker.exists() else "Re-run: antctl init",
        )
    )
    results.extend(_check_workspace_permissions(ant_dir))
    results.extend(_check_workspace_config(ant_dir))
    results.extend(_check_workspace_db(ant_dir))
    results.append(_check_checkpoint_db(ant_dir))
    results.extend(_check_audit_dir(ant_dir))
    return results


def _check_workspace_permissions(ant_dir: Path) -> list[CheckResult]:
    try:
        probe = ant_dir / ".doctor_probe_tmp"
        probe.write_bytes(b"")
        probe.unlink()
        return [
            CheckResult(
                check_id="workspace.permissions",
                status=STATUS_PASS,
                message="Workspace directory is readable and writable",
            )
        ]
    except OSError as exc:
        return [
            CheckResult(
                check_id="workspace.permissions",
                status=STATUS_FAIL,
                message=f"Cannot write to workspace directory: {exc}",
                remediation="Check directory permissions for .ant/",
            )
        ]


def _check_workspace_config(ant_dir: Path) -> list[CheckResult]:
    config_path = ant_dir / "config.yaml"
    try:
        if config_path.exists():
            load_document(config_path)
            return [
                CheckResult(
                    check_id="workspace.config",
                    status=STATUS_PASS,
                    message="config.yaml parses successfully",
                )
            ]
        return [
            CheckResult(
                check_id="workspace.config",
                status=STATUS_WARN,
                message="config.yaml not found - using defaults",
                remediation="Run: antctl configure",
            )
        ]
    except Exception as exc:
        return [
            CheckResult(
                check_id="workspace.config",
                status=STATUS_FAIL,
                message=f"config.yaml invalid: {exc}",
                remediation="Run: antctl configure  or fix .ant/config.yaml",
            )
        ]


def _check_workspace_db(ant_dir: Path) -> list[CheckResult]:
    db_path = ant_dir / DATABASE_FILENAME
    inspector = SqliteDatabaseInspector()
    if not db_path.exists():
        return [
            CheckResult(
                check_id="workspace.db",
                status=STATUS_WARN,
                message="state.sqlite not found",
                remediation="Run: antctl init",
            )
        ]
    schema_ver = inspector.schema_version(db_path)
    if schema_ver is None:
        return [
            CheckResult(
                check_id="workspace.db",
                status=STATUS_FAIL,
                message="state.sqlite exists but has no schema_migrations table",
                remediation="Run: antctl init  to re-bootstrap the database",
            )
        ]
    if schema_ver < EXPECTED_DB_SCHEMA_VERSION:
        return [
            CheckResult(
                check_id="workspace.db",
                status=STATUS_FAIL,
                message=(
                    f"state.sqlite schema v{schema_ver} (expected v{EXPECTED_DB_SCHEMA_VERSION})"
                ),
                remediation="Run: antctl init  to migrate the database",
            )
        ]
    return [
        CheckResult(
            check_id="workspace.db",
            status=STATUS_PASS,
            message=f"state.sqlite schema v{schema_ver}",
        )
    ]


def _check_checkpoint_db(ant_dir: Path) -> CheckResult:
    cp_path = ant_dir / CHECKPOINT_DB_FILENAME
    return CheckResult(
        check_id="workspace.checkpoint_db",
        status=STATUS_PASS if cp_path.exists() else STATUS_WARN,
        message=(
            "checkpoints.sqlite present"
            if cp_path.exists()
            else "checkpoints.sqlite not found (created on first workflow run)"
        ),
    )


def _check_audit_dir(ant_dir: Path) -> list[CheckResult]:
    logs_dir = ant_dir / "logs"
    if not logs_dir.exists():
        return [
            CheckResult(
                check_id="workspace.audit_dir",
                status=STATUS_WARN,
                message="logs/ directory missing",
                remediation="Run: antctl init",
            )
        ]
    try:
        probe = logs_dir / ".doctor_probe_tmp"
        probe.write_bytes(b"")
        probe.unlink()
        return [
            CheckResult(
                check_id="workspace.audit_dir",
                status=STATUS_PASS,
                message="logs/ directory writable",
            )
        ]
    except OSError as exc:
        return [
            CheckResult(
                check_id="workspace.audit_dir",
                status=STATUS_FAIL,
                message=f"logs/ not writable: {exc}",
                remediation="Check directory permissions for .ant/logs/",
            )
        ]


def check_provider(search_root: Path) -> list[CheckResult]:
    results: list[CheckResult] = []
    root = find_nest(search_root)
    if root is None:
        results.append(
            CheckResult(
                check_id="provider.configured",
                status=STATUS_SKIP,
                message="No workspace - skipping provider checks",
            )
        )
        return results
    config_path = root / ANT_DIRNAME / "config.yaml"
    try:
        file_data = load_document(config_path)
        config = ConfigResolver().resolve(file_data=file_data, env={})
    except Exception:
        results.append(
            CheckResult(
                check_id="provider.configured",
                status=STATUS_SKIP,
                message="Config invalid - skipping provider checks",
            )
        )
        return results
    queen = config.models.queen
    local = config.models.local
    if queen is None and local is None:
        results.append(
            CheckResult(
                check_id="provider.configured",
                status=STATUS_WARN,
                message="No model endpoints configured",
                remediation="Run: antctl configure",
            )
        )
        return results
    results.append(
        CheckResult(
            check_id="provider.configured",
            status=STATUS_PASS,
            message="At least one model endpoint configured",
        )
    )
    for role, endpoint in (("queen", queen), ("local", local)):
        if endpoint is None:
            continue
        provider = endpoint.provider
        if provider not in CONFIGURE_SUPPORTED_PROVIDERS:
            results.append(
                CheckResult(
                    check_id=f"provider.{role}.provider",
                    status=STATUS_WARN,
                    message=f"{role}: provider '{provider}' is not a known supported provider",
                )
            )
            continue
        results.append(
            CheckResult(
                check_id=f"provider.{role}.provider",
                status=STATUS_PASS,
                message=f"{role}: provider={provider} model={endpoint.model}",
            )
        )
        key_env = PROVIDER_KEY_ENV.get(provider)
        if key_env is None:
            results.append(
                CheckResult(
                    check_id=f"provider.{role}.credential",
                    status=STATUS_PASS,
                    message=f"{role}: {provider} requires no API key",
                )
            )
        else:
            value = os.environ.get(key_env)
            if value:
                results.append(
                    CheckResult(
                        check_id=f"provider.{role}.credential",
                        status=STATUS_PASS,
                        message=f"{role}: {key_env} is set",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        check_id=f"provider.{role}.credential",
                        status=STATUS_WARN,
                        message=f"{role}: {key_env} is not set",
                        remediation=f"Set environment variable: {key_env}=<your key>",
                    )
                )
    return results
