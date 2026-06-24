"""CP0 redaction tests: detection coverage, determinism, no secret leakage.

All secret values below are obviously fake fixtures, never real credentials.
"""

from __future__ import annotations

import pytest

from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.security.redaction.patterns import SecretPattern
from ant_orchestrator.security.redaction.redactor import (
    REDACTION_REPLACEMENT_MARKER,
    RedactionMark,
    RedactionResult,
    Redactor,
)

FAKE_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIBOwIBAAJBAKfake0000fakeKEYmaterialNOTreal1234567890abcdEFGH\n"
    "-----END RSA PRIVATE KEY-----"
)
FAKE_OPENAI = "sk-" + "A" * 40
FAKE_GH = "ghp_" + "B" * 36
FAKE_AWS = "AKIA" + "Z" * 16
FAKE_BEARER_TOKEN = "abcDEF1234ghiJKL"


def _patterns(result: RedactionResult) -> set[SecretPattern]:
    return {mark.pattern for mark in result.marks}


def test_redacts_pem_private_key() -> None:
    result = Redactor().redact(f"here is a key:\n{FAKE_PEM}\ndone")
    assert SecretPattern.PEM_PRIVATE_KEY in _patterns(result)
    assert "PRIVATE KEY" not in result.text
    assert "fakeKEYmaterial" not in result.text
    assert REDACTION_REPLACEMENT_MARKER in result.text


def test_redacts_openai_style_api_token() -> None:
    result = Redactor().redact(f"the key is {FAKE_OPENAI} ok")
    assert SecretPattern.API_TOKEN in _patterns(result)
    assert FAKE_OPENAI not in result.text
    assert "sk-" not in result.text


def test_redacts_github_style_token() -> None:
    result = Redactor().redact(f"token={FAKE_GH}")
    assert SecretPattern.API_TOKEN in _patterns(result)
    assert FAKE_GH not in result.text


def test_redacts_aws_access_key() -> None:
    result = Redactor().redact(f"aws id {FAKE_AWS} here")
    assert SecretPattern.AWS_KEY in _patterns(result)
    assert FAKE_AWS not in result.text


def test_redacts_bearer_token_keeps_scheme() -> None:
    result = Redactor().redact(f"Authorization: Bearer {FAKE_BEARER_TOKEN}")
    assert SecretPattern.BEARER in _patterns(result)
    assert FAKE_BEARER_TOKEN not in result.text
    assert "Bearer" in result.text  # the non-secret scheme word is preserved


def test_redacts_env_assignment_value_keeps_key() -> None:
    result = Redactor().redact("DB_PASSWORD=supersecretvalue123")
    assert SecretPattern.ENV_ASSIGNMENT in _patterns(result)
    assert "supersecretvalue123" not in result.text
    assert "DB_PASSWORD=" in result.text


def test_redacts_generic_credential() -> None:
    result = Redactor().redact("password: hunter2longvalue")
    assert SecretPattern.GENERIC_CREDENTIAL in _patterns(result)
    assert "hunter2longvalue" not in result.text


def test_multiple_distinct_secrets_each_marked() -> None:
    text = f"{FAKE_PEM}\nAPI=zz {FAKE_OPENAI} aws {FAKE_AWS}"
    result = Redactor().redact(text)
    assert {
        SecretPattern.PEM_PRIVATE_KEY,
        SecretPattern.API_TOKEN,
        SecretPattern.AWS_KEY,
    } <= _patterns(result)
    assert FAKE_OPENAI not in result.text
    assert FAKE_AWS not in result.text


def test_repeated_secret_counts_each_occurrence() -> None:
    result = Redactor().redact(f"{FAKE_AWS} and {FAKE_AWS}")
    aws_marks = [m for m in result.marks if m.pattern is SecretPattern.AWS_KEY]
    assert len(aws_marks) == 1
    assert aws_marks[0].count == 2


def test_empty_input_is_valid_and_unmarked() -> None:
    result = Redactor().redact("")
    assert result.text == ""
    assert result.marks == ()


def test_normal_text_is_not_modified() -> None:
    text = "All systems nominal; total = 42 items processed."
    result = Redactor().redact(text)
    assert result.text == text
    assert result.marks == ()


def test_word_token_without_assignment_is_not_a_false_positive() -> None:
    result = Redactor().redact("This token is just a word in a sentence here.")
    assert result.marks == ()


def test_unicode_is_preserved_while_secret_redacted() -> None:
    result = Redactor().redact(f"café résumé {FAKE_OPENAI}")
    assert "café résumé" in result.text
    assert FAKE_OPENAI not in result.text


def test_redaction_mark_holds_only_pattern_and_count() -> None:
    mark = RedactionMark(SecretPattern.BEARER, 3)
    assert mark.pattern is SecretPattern.BEARER
    assert mark.count == 3


def test_redaction_mark_rejects_non_positive_count() -> None:
    with pytest.raises(InvariantViolation):
        RedactionMark(SecretPattern.BEARER, 0)


def test_redactor_rejects_empty_marker() -> None:
    with pytest.raises(InvariantViolation):
        Redactor(marker="")
