"""Secret detection patterns for content redaction (CP0).

Pure, stdlib-only. Each rule maps a :class:`SecretPattern` to a compiled regex and
the capture group whose text must be replaced (group ``0`` = the whole match).
Patterns are heuristic and tuned for the MVP: they aim to catch common secret
shapes (PEM keys, provider tokens, env assignments, credentials) with a low
false-positive rate. The matched secret value is never stored or returned — only
the pattern label and a count (see ``security.redaction.redactor``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class SecretPattern(Enum):
    """Category of a detected secret (label only — never the secret value)."""

    ENV_ASSIGNMENT = "env_assignment"
    PEM_PRIVATE_KEY = "pem_private_key"
    API_TOKEN = "api_token"
    BEARER = "bearer"
    AWS_KEY = "aws_key"
    GENERIC_CREDENTIAL = "generic_credential"


@dataclass(frozen=True, slots=True)
class SecretRule:
    """A compiled detector: which pattern, its regex, and the group to redact."""

    pattern: SecretPattern
    regex: re.Pattern[str]
    # 0 = replace the whole match; >= 1 = replace only that capture group, keeping
    # the surrounding non-secret prefix (e.g. the ``KEY=`` part of an assignment).
    redact_group: int


# Order matters: structural / specific patterns run first so their matches are
# redacted before broader generic patterns scan the (already redacted) text.
DEFAULT_SECRET_RULES: tuple[SecretRule, ...] = (
    SecretRule(
        SecretPattern.PEM_PRIVATE_KEY,
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"
            r".*?-----END (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----",
            re.DOTALL,
        ),
        0,
    ),
    SecretRule(
        SecretPattern.AWS_KEY,
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
        0,
    ),
    SecretRule(
        SecretPattern.API_TOKEN,
        re.compile(
            r"\b(?:sk-[A-Za-z0-9]{20,}"
            r"|gh[pousr]_[A-Za-z0-9]{20,}"
            r"|xox[baprs]-[A-Za-z0-9-]{10,})\b"
        ),
        0,
    ),
    SecretRule(
        SecretPattern.BEARER,
        re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._~+/=-]{8,})"),
        1,
    ),
    SecretRule(
        SecretPattern.ENV_ASSIGNMENT,
        re.compile(
            r"(?im)^[ \t]*(?:export[ \t]+)?[A-Z0-9_]*"
            r"(?:SECRET|TOKEN|PASSWORD|PASSWD|API[_-]?KEY|ACCESS[_-]?KEY"
            r"|PRIVATE[_-]?KEY|CREDENTIAL)[A-Z0-9_]*[ \t]*=[ \t]*(\S+)"
        ),
        1,
    ),
    SecretRule(
        SecretPattern.GENERIC_CREDENTIAL,
        re.compile(
            r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|credential)\b"
            r"[ \t]*[:=][ \t]*[\"']?([^\s\"']{4,})"
        ),
        1,
    ),
)
