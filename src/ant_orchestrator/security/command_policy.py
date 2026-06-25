"""Command policy — pure argv allowlist guard for shell execution (CP2).

Decides whether a structured argv command is permitted based on executable
allowlist with exact-match rules, command-specific argument prefix policy,
shell wrapper deny list, and metacharacter/control character detection.

Pure policy: no process execution, no audit, no filesystem I/O, no subprocess,
no adapter import. CP3 enforces decisions and writes audit evidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.core.domain.errors import InvariantViolation

# ======================================================================
# Deny taxonomy
# ======================================================================


class CommandDenyReason(Enum):
    """Why a command request was denied (typed — no free-form string)."""

    EMPTY_ARGV = "empty_argv"
    EMPTY_EXECUTABLE = "empty_executable"
    EXECUTABLE_NOT_ALLOWED = "executable_not_allowed"
    EXECUTABLE_PATH_NOT_ALLOWED = "executable_path_not_allowed"
    SHELL_WRAPPER_NOT_ALLOWED = "shell_wrapper_not_allowed"
    SHELL_METACHARACTER = "shell_metacharacter"
    ARGUMENT_POLICY_VIOLATION = "argument_policy_violation"
    CONTROL_CHARACTER = "control_character"


# ======================================================================
# Security constants
# ======================================================================

_SHELL_WRAPPER_NAMES: Final[frozenset[str]] = frozenset(
    {
        "sh",
        "bash",
        "zsh",
        "dash",
        "cmd",
        "cmd.exe",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
    }
)

_SHELL_METACHAR_TOKENS: Final[tuple[str, ...]] = (
    "&&",
    "||",
    "|",
    ";",
    ">",
    "<",
    "$(",
    "`",
)

_CONTROL_CHARS: Final[frozenset[str]] = frozenset({"\x00", "\n", "\r"})


# ======================================================================
# Value objects
# ======================================================================


@dataclass(frozen=True, slots=True)
class CommandRule:
    """Per-executable argument policy. Immutable.

    ``allowed_arg_prefixes``: each inner tuple is a valid argument prefix sequence.
    Empty outer tuple means no invocation is permitted for this executable.
    An inner empty tuple ``()`` permits bare invocation (no arguments).

    ``allow_trailing_args``: when True, additional arguments after a matched prefix
    are accepted; when False, arguments must exactly equal a prefix.

    ``forbidden_args``: arguments denied even when a prefix matches (exact match).
    """

    executable: str
    allowed_arg_prefixes: tuple[tuple[str, ...], ...]
    allow_trailing_args: bool = True
    forbidden_args: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.executable:
            raise InvariantViolation("CommandRule.executable must be non-empty")


@dataclass(frozen=True, slots=True)
class CommandDecision:
    """Outcome of a command policy check."""

    decision: PolicyDecision
    reason: CommandDenyReason | None

    def __post_init__(self) -> None:
        if self.decision is PolicyDecision.ALLOW:
            if self.reason is not None:
                raise InvariantViolation("ALLOW must not carry a deny reason")
        else:
            if self.reason is None:
                raise InvariantViolation("DENY must carry a reason")


# ======================================================================
# Policy
# ======================================================================


class CommandPolicy:
    """Stateless, deterministic command argv guard.

    Takes structured argv (never raw shell string). Does not execute processes,
    write audit, or perform filesystem I/O. CP3 uses the decision to enforce.
    """

    def __init__(self, rules: tuple[CommandRule, ...] = ()) -> None:
        self._rules: dict[str, CommandRule] = {r.executable: r for r in rules}

    def check(self, argv: tuple[str, ...]) -> CommandDecision:
        """Return ALLOW or DENY with typed reason."""
        if not argv:
            return _deny(CommandDenyReason.EMPTY_ARGV)

        executable = argv[0]
        if not executable.strip():
            return _deny(CommandDenyReason.EMPTY_EXECUTABLE)

        if _any_has_control_char(argv):
            return _deny(CommandDenyReason.CONTROL_CHARACTER)

        if _any_has_metachar(argv):
            return _deny(CommandDenyReason.SHELL_METACHARACTER)

        if executable.lower() in _SHELL_WRAPPER_NAMES:
            return _deny(CommandDenyReason.SHELL_WRAPPER_NOT_ALLOWED)

        rule = self._rules.get(executable)
        if rule is None:
            if _has_path_separator(executable):
                return _deny(CommandDenyReason.EXECUTABLE_PATH_NOT_ALLOWED)
            return _deny(CommandDenyReason.EXECUTABLE_NOT_ALLOWED)

        args = argv[1:]

        if rule.forbidden_args and any(a in rule.forbidden_args for a in args):
            return _deny(CommandDenyReason.ARGUMENT_POLICY_VIOLATION)

        if not _args_match_prefixes(args, rule.allowed_arg_prefixes, rule.allow_trailing_args):
            return _deny(CommandDenyReason.ARGUMENT_POLICY_VIOLATION)

        return _allow()


# ======================================================================
# Helpers (module-private)
# ======================================================================


def _has_path_separator(s: str) -> bool:
    return "/" in s or "\\" in s


def _any_has_control_char(argv: tuple[str, ...]) -> bool:
    for element in argv:
        for ch in element:
            if ch in _CONTROL_CHARS:
                return True
    return False


def _any_has_metachar(argv: tuple[str, ...]) -> bool:
    for element in argv:
        for token in _SHELL_METACHAR_TOKENS:
            if token in element:
                return True
    return False


def _args_match_prefixes(
    args: tuple[str, ...],
    prefixes: tuple[tuple[str, ...], ...],
    allow_trailing: bool,
) -> bool:
    for prefix in prefixes:
        n = len(prefix)
        if len(args) < n:
            continue
        if args[:n] == prefix:
            if allow_trailing or len(args) == n:
                return True
    return False


def _allow() -> CommandDecision:
    return CommandDecision(PolicyDecision.ALLOW, None)


def _deny(reason: CommandDenyReason) -> CommandDecision:
    return CommandDecision(PolicyDecision.DENY, reason)
