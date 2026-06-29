"""Phase 8 CP5 — Doctor shared types and installation checks.

CheckResult, status constants, overall_status, and the installation checks.
Workspace/provider checks live in cp5_doctor_workspace.py.
"""

from __future__ import annotations

import os
import platform
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ant_orchestrator.config.constants import ANT_CLI_VERSION

STATUS_PASS: Final = "PASS"
STATUS_WARN: Final = "WARN"
STATUS_FAIL: Final = "FAIL"
STATUS_SKIP: Final = "SKIP"


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One health-check observation."""

    check_id: str
    status: str
    message: str
    remediation: str | None = None


def overall_status(checks: list[CheckResult]) -> str:
    if any(c.status == STATUS_FAIL for c in checks):
        return STATUS_FAIL
    if any(c.status == STATUS_WARN for c in checks):
        return STATUS_WARN
    return STATUS_PASS


# ---------------------------------------------------------------------------
# Installation checks
# ---------------------------------------------------------------------------


def antctl_exe_path() -> Path:
    scripts_dir = Path(sysconfig.get_path("scripts"))
    suffix = ".exe" if os.name == "nt" else ""
    return scripts_dir / f"antctl{suffix}"


def ant_exe_path() -> Path:
    scripts_dir = Path(sysconfig.get_path("scripts"))
    suffix = ".exe" if os.name == "nt" else ""
    return scripts_dir / f"ant{suffix}"


def check_installation() -> list[CheckResult]:
    results: list[CheckResult] = []
    results.append(
        CheckResult(
            check_id="install.version",
            status=STATUS_PASS,
            message=f"antctl {ANT_CLI_VERSION}",
        )
    )
    sys_os = platform.system()
    arch = platform.machine()
    results.append(
        CheckResult(
            check_id="install.platform",
            status=STATUS_PASS,
            message=f"{sys_os} {arch}",
        )
    )
    if sys_os == "Windows" and ("64" in arch or arch == "AMD64"):
        win_status, win_msg = STATUS_PASS, "Windows x64 - supported platform"
    elif sys_os == "Windows":
        win_status = STATUS_WARN
        win_msg = f"Windows {arch} - only x64 is fully supported in Phase 8"
    else:
        win_status = STATUS_WARN
        win_msg = f"{sys_os} - Windows x64 is the supported Phase 8 platform"
    results.append(
        CheckResult(check_id="install.platform_support", status=win_status, message=win_msg)
    )
    antctl_path = antctl_exe_path()
    if antctl_path.exists():
        results.append(
            CheckResult(
                check_id="install.antctl_executable",
                status=STATUS_PASS,
                message=f"antctl found at {antctl_path}",
            )
        )
    else:
        results.append(
            CheckResult(
                check_id="install.antctl_executable",
                status=STATUS_FAIL,
                message=f"antctl not found at {antctl_path}",
                remediation='Run: python -m pip install -e ".[dev]"',
            )
        )
    ant_path = ant_exe_path()
    if ant_path.exists():
        results.append(
            CheckResult(
                check_id="install.ant_legacy_executable",
                status=STATUS_PASS,
                message=f"ant (legacy alias) found at {ant_path}",
            )
        )
    else:
        results.append(
            CheckResult(
                check_id="install.ant_legacy_executable",
                status=STATUS_WARN,
                message=f"ant (legacy alias) not found at {ant_path}",
                remediation='Run: python -m pip install -e ".[dev]"',
            )
        )
    results.append(_check_apache_ant_conflict(ant_path))
    return results


def _check_apache_ant_conflict(our_ant: Path) -> CheckResult:
    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    for entry in path_dirs:
        candidate = Path(entry)
        if candidate == our_ant.parent:
            continue
        for name in ("ant", "ant.bat", "ant.cmd", "ant.exe"):
            if (candidate / name).exists():
                return CheckResult(
                    check_id="install.apache_ant_conflict",
                    status=STATUS_WARN,
                    message=f"Apache Ant binary found at {candidate / name}",
                    remediation=(
                        "Ensure 'antctl' is used for this tool; "
                        "the legacy 'ant' alias may conflict with Apache Ant."
                    ),
                )
    return CheckResult(
        check_id="install.apache_ant_conflict",
        status=STATUS_PASS,
        message="No conflicting Apache Ant binary detected",
    )
