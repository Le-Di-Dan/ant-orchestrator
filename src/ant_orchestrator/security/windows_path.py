"""Pure, cross-platform lexical guard for Windows-ambiguous paths (PHASE_5_PLAN CP3).

A Documentation Ant target must be a normalized, workspace-relative path. These
checks are purely lexical (no filesystem, no host ``Path.resolve``) so they run
identically on POSIX CI and on Windows. Anything ambiguous fails closed: the caller
denies with ``DenyReason.UNSAFE_WINDOWS_PATH`` before any canonicalization.

The reserved-name and trailing dot/space checks are applied on every platform (not
gated on the host OS): a target that would alias a different file on Windows is
rejected everywhere so a document authored on POSIX can never become unsafe later.
"""

from __future__ import annotations

from typing import Final

# Windows reserved device names (case-insensitive), matched on a component's stem.
RESERVED_DEVICE_NAMES: Final[frozenset[str]] = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def normalize_separators(requested: str) -> str:
    """Fold ``\\`` to ``/`` so separators are interpreted consistently everywhere."""
    return requested.replace("\\", "/")


def is_lexically_unsafe(normalized: str) -> bool:
    """Return True if ``normalized`` is a Windows-ambiguous / non-relative form.

    Rejects: any colon (drive letter, ADS/stream), a UNC/device prefix (``//`` after
    separator folding, covering ``\\\\server``, ``\\\\?\\``, ``\\\\.\\``), a reserved
    device-name component, and a component with a trailing dot or space.
    """
    if ":" in normalized:
        return True
    if normalized.startswith("//"):
        return True
    for component in normalized.split("/"):
        if not component or component in (".", ".."):
            continue
        if component[-1] in (".", " "):
            return True
        if component.split(".")[0].upper() in RESERVED_DEVICE_NAMES:
            return True
    return False
