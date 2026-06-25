"""CP2 command policy tests: allowlist, spoofing, wrappers, metachar, interpreter.

All tests use explicit rule fixtures; no production command set is hard-coded.
"""

from __future__ import annotations

import pytest

from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.security.command_policy import (
    CommandDecision,
    CommandDenyReason,
    CommandPolicy,
    CommandRule,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _git_rule() -> CommandRule:
    return CommandRule(
        executable="git",
        allowed_arg_prefixes=(("status",), ("log",), ("diff",)),
        allow_trailing_args=True,
    )


def _python_rule() -> CommandRule:
    return CommandRule(
        executable="python",
        allowed_arg_prefixes=(("-m", "pytest"), ("-m", "scripts.quality.gate")),
        allow_trailing_args=True,
    )


def _policy(*rules: CommandRule) -> CommandPolicy:
    return CommandPolicy(rules)


# ------------------------------------------------------------------
# §20.1 Basic decisions
# ------------------------------------------------------------------


class TestBasicDecisions:
    def test_empty_argv(self) -> None:
        d = _policy(_git_rule()).check(())
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.EMPTY_ARGV

    def test_empty_executable(self) -> None:
        d = _policy(_git_rule()).check(("",))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.EMPTY_EXECUTABLE

    def test_whitespace_executable(self) -> None:
        d = _policy(_git_rule()).check(("  ",))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.EMPTY_EXECUTABLE

    def test_exact_allowed(self) -> None:
        d = _policy(_git_rule()).check(("git", "status"))
        assert d.decision is PolicyDecision.ALLOW

    def test_disallowed_executable(self) -> None:
        d = _policy(_git_rule()).check(("curl", "http://example.com"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.EXECUTABLE_NOT_ALLOWED

    def test_bare_invocation_allowed(self) -> None:
        rule = CommandRule(executable="ls", allowed_arg_prefixes=((),), allow_trailing_args=False)
        d = _policy(rule).check(("ls",))
        assert d.decision is PolicyDecision.ALLOW

    def test_args_matching_prefix(self) -> None:
        d = _policy(_git_rule()).check(("git", "log", "--oneline"))
        assert d.decision is PolicyDecision.ALLOW

    def test_args_not_matching_prefix(self) -> None:
        d = _policy(_git_rule()).check(("git", "push", "origin"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.ARGUMENT_POLICY_VIOLATION

    def test_trailing_denied_when_disallowed(self) -> None:
        rule = CommandRule(
            executable="git", allowed_arg_prefixes=(("status",),), allow_trailing_args=False
        )
        d = _policy(rule).check(("git", "status", "--short"))
        assert d.decision is PolicyDecision.DENY

    def test_forbidden_arg_denied(self) -> None:
        rule = CommandRule(
            executable="tool",
            allowed_arg_prefixes=(("run",),),
            allow_trailing_args=True,
            forbidden_args=frozenset({"--dangerous"}),
        )
        d = _policy(rule).check(("tool", "run", "--dangerous"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.ARGUMENT_POLICY_VIOLATION

    def test_empty_prefixes_deny_all_args(self) -> None:
        rule = CommandRule(executable="x", allowed_arg_prefixes=())
        d = _policy(rule).check(("x",))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.ARGUMENT_POLICY_VIOLATION


# ------------------------------------------------------------------
# §20.2 Executable spoofing
# ------------------------------------------------------------------


class TestExecutableSpoofing:
    def test_tmp_git_denied(self) -> None:
        d = _policy(_git_rule()).check(("/tmp/git",))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.EXECUTABLE_PATH_NOT_ALLOWED

    def test_dot_slash_denied(self) -> None:
        d = _policy(_git_rule()).check(("./git", "status"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.EXECUTABLE_PATH_NOT_ALLOWED

    def test_dot_dot_slash_denied(self) -> None:
        d = _policy(_git_rule()).check(("../git", "status"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.EXECUTABLE_PATH_NOT_ALLOWED

    def test_workspace_python_denied(self) -> None:
        d = _policy(_python_rule()).check(("workspace/python", "-m", "pytest"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.EXECUTABLE_PATH_NOT_ALLOWED

    def test_prefix_collision_executable(self) -> None:
        d = _policy(_git_rule()).check(("git-lfs", "push"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.EXECUTABLE_NOT_ALLOWED

    def test_absolute_needs_exact_rule(self) -> None:
        rule = CommandRule(executable="/usr/bin/git", allowed_arg_prefixes=(("status",),))
        d = _policy(rule).check(("/usr/bin/git", "status"))
        assert d.decision is PolicyDecision.ALLOW

    def test_absolute_wrong_path_denied(self) -> None:
        rule = CommandRule(executable="/usr/bin/git", allowed_arg_prefixes=(("status",),))
        d = _policy(rule).check(("/tmp/git", "status"))
        assert d.decision is PolicyDecision.DENY

    def test_no_basename_match(self) -> None:
        d = _policy(_git_rule()).check(("/usr/local/bin/git", "status"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.EXECUTABLE_PATH_NOT_ALLOWED

    def test_windows_path_denied(self) -> None:
        d = _policy(_git_rule()).check(("C:\\Windows\\git.exe", "status"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.EXECUTABLE_PATH_NOT_ALLOWED


# ------------------------------------------------------------------
# §20.3 Shell wrappers
# ------------------------------------------------------------------


class TestShellWrappers:
    @pytest.mark.parametrize(
        "wrapper,args",
        [
            ("sh", ("-c", "echo hi")),
            ("bash", ("-c", "echo hi")),
            ("cmd", ("/c", "dir")),
            ("cmd.exe", ("/c", "dir")),
            ("powershell", ("-Command", "Get-Process")),
            ("powershell", ("-EncodedCommand", "base64data")),
            ("pwsh", ("-Command", "Get-Process")),
        ],
    )
    def test_wrapper_denied(self, wrapper: str, args: tuple[str, ...]) -> None:
        rule = CommandRule(executable=wrapper, allowed_arg_prefixes=(args,))
        d = _policy(rule).check((wrapper, *args))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.SHELL_WRAPPER_NOT_ALLOWED

    def test_case_insensitive(self) -> None:
        d = _policy().check(("BASH", "-c", "echo hi"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.SHELL_WRAPPER_NOT_ALLOWED

    def test_wrapper_denied_even_in_allowlist(self) -> None:
        rule = CommandRule(executable="sh", allowed_arg_prefixes=((),), allow_trailing_args=True)
        d = _policy(rule).check(("sh",))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.SHELL_WRAPPER_NOT_ALLOWED


# ------------------------------------------------------------------
# §20.4 Metacharacters / control
# ------------------------------------------------------------------


class TestMetacharControl:
    @pytest.mark.parametrize("token", ["&&", "||", "|", ";", ">", "<", "$(", "`"])
    def test_metachar_in_arg(self, token: str) -> None:
        d = _policy(_git_rule()).check(("git", "status", f"foo{token}bar"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.SHELL_METACHARACTER

    def test_metachar_in_executable(self) -> None:
        d = _policy().check(("git;rm", "-rf"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.SHELL_METACHARACTER

    def test_metachar_hidden_in_long_arg(self) -> None:
        long_arg = "a" * 100 + "&&" + "b" * 100
        d = _policy(_git_rule()).check(("git", "status", long_arg))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.SHELL_METACHARACTER

    @pytest.mark.parametrize("ctrl", ["\x00", "\n", "\r"])
    def test_control_char_denied(self, ctrl: str) -> None:
        d = _policy(_git_rule()).check(("git", "status", f"file{ctrl}evil"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.CONTROL_CHARACTER

    def test_control_takes_priority_over_metachar(self) -> None:
        d = _policy(_git_rule()).check(("git", "status", "\n&&"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.CONTROL_CHARACTER


# ------------------------------------------------------------------
# §20.5 Interpreter rules
# ------------------------------------------------------------------


class TestInterpreterRules:
    def test_python_c_denied(self) -> None:
        d = _policy(_python_rule()).check(("python", "-c", "import os"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.ARGUMENT_POLICY_VIOLATION

    def test_python_m_pytest_allowed(self) -> None:
        d = _policy(_python_rule()).check(("python", "-m", "pytest", "-v"))
        assert d.decision is PolicyDecision.ALLOW

    def test_python_m_quality_gate_allowed(self) -> None:
        d = _policy(_python_rule()).check(("python", "-m", "scripts.quality.gate"))
        assert d.decision is PolicyDecision.ALLOW

    def test_python_m_unlisted_module_denied(self) -> None:
        d = _policy(_python_rule()).check(("python", "-m", "http.server"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.ARGUMENT_POLICY_VIOLATION

    def test_node_eval_denied(self) -> None:
        rule = CommandRule(executable="node", allowed_arg_prefixes=(("script.js",),))
        d = _policy(rule).check(("node", "-e", "process.exit(1)"))
        assert d.decision is PolicyDecision.DENY

    def test_node_eval_long_form_denied(self) -> None:
        rule = CommandRule(executable="node", allowed_arg_prefixes=(("script.js",),))
        d = _policy(rule).check(("node", "--eval", "process.exit(1)"))
        assert d.decision is PolicyDecision.DENY

    def test_git_alias_exec_denied(self) -> None:
        d = _policy(_git_rule()).check(("git", "-c", "alias.x=!rm -rf /", "x"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.ARGUMENT_POLICY_VIOLATION

    def test_find_exec_semicolon_metachar(self) -> None:
        rule = CommandRule(
            executable="find", allowed_arg_prefixes=((".",),), allow_trailing_args=False
        )
        d = _policy(rule).check(("find", ".", "-exec", "rm", "{}", ";"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.SHELL_METACHARACTER

    def test_find_exec_plus_arg_violation(self) -> None:
        rule = CommandRule(
            executable="find", allowed_arg_prefixes=((".",),), allow_trailing_args=False
        )
        d = _policy(rule).check(("find", ".", "-exec", "rm", "{}", "+"))
        assert d.decision is PolicyDecision.DENY
        assert d.reason is CommandDenyReason.ARGUMENT_POLICY_VIOLATION


# ------------------------------------------------------------------
# §20.6 Legitimate arguments
# ------------------------------------------------------------------


class TestLegitimateArguments:
    def test_hyphenated_options(self) -> None:
        d = _policy(_git_rule()).check(("git", "log", "--oneline", "--graph"))
        assert d.decision is PolicyDecision.ALLOW

    def test_dotted_module_name(self) -> None:
        d = _policy(_python_rule()).check(("python", "-m", "scripts.quality.gate"))
        assert d.decision is PolicyDecision.ALLOW

    def test_file_path_argument(self) -> None:
        d = _policy(_git_rule()).check(("git", "diff", "src/main.py"))
        assert d.decision is PolicyDecision.ALLOW

    def test_space_in_argv_element(self) -> None:
        d = _policy(_git_rule()).check(("git", "log", "--format=Author: %an"))
        assert d.decision is PolicyDecision.ALLOW

    def test_unicode_argument(self) -> None:
        d = _policy(_git_rule()).check(("git", "log", "--author=日本語"))
        assert d.decision is PolicyDecision.ALLOW

    def test_colon_in_argument(self) -> None:
        d = _policy(_git_rule()).check(("git", "diff", "HEAD:file.txt"))
        assert d.decision is PolicyDecision.ALLOW

    def test_empty_trailing_arg(self) -> None:
        d = _policy(_git_rule()).check(("git", "status", ""))
        assert d.decision is PolicyDecision.ALLOW

    def test_policy_deterministic(self) -> None:
        p = _policy(_git_rule())
        d1 = p.check(("git", "status"))
        d2 = p.check(("git", "status"))
        assert d1.decision == d2.decision


# ------------------------------------------------------------------
# §20.7 Contract invariants
# ------------------------------------------------------------------


class TestContractInvariants:
    def test_allow_must_not_have_reason(self) -> None:
        with pytest.raises(InvariantViolation):
            CommandDecision(PolicyDecision.ALLOW, CommandDenyReason.EMPTY_ARGV)

    def test_deny_must_have_reason(self) -> None:
        with pytest.raises(InvariantViolation):
            CommandDecision(PolicyDecision.DENY, None)

    def test_empty_executable_rule_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            CommandRule(executable="", allowed_arg_prefixes=())
