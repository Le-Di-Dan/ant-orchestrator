"""End-to-end validation that the installed ``ant`` console script works.

Resolves the console-scripts directory of the interpreter running the tests (so it
does not depend on shell PATH or an activated virtual environment) and runs the
``ant`` executable. A missing executable is a packaging failure and fails the test
(never skipped).
"""

import os
import subprocess
import sysconfig
from pathlib import Path

_MISSING_MESSAGE = (
    "Console script 'ant' not found at {exe}. Run "
    "'python -m pip install -e \".[dev]\"'; the editable installation or the "
    "[project.scripts] entry point may be invalid."
)


def _ant_executable() -> Path:
    scripts_dir = Path(sysconfig.get_path("scripts"))
    name = "ant.exe" if os.name == "nt" else "ant"
    return scripts_dir / name


def test_console_script_exists() -> None:
    exe = _ant_executable()
    assert exe.exists(), _MISSING_MESSAGE.format(exe=exe)


def test_console_script_help_runs() -> None:
    exe = _ant_executable()
    assert exe.exists(), _MISSING_MESSAGE.format(exe=exe)
    result = subprocess.run(
        [str(exe), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "Usage" in result.stdout
