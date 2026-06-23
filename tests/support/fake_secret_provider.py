"""FakeSecretProvider — a scripted in-memory SecretProvider test double (CP2).

Test-only: lives outside ``src/`` and is never imported by production code. Its
``repr`` never reveals stored secrets.
"""

from __future__ import annotations


class FakeSecretProvider:
    """Returns scripted secrets; missing or empty values resolve to ``None``."""

    def __init__(self, secrets: dict[str, str] | None = None) -> None:
        self._secrets = dict(secrets) if secrets is not None else {}

    def get(self, name: str) -> str | None:
        value = self._secrets.get(name)
        if not value:
            return None
        return value

    def __repr__(self) -> str:
        return f"FakeSecretProvider(<{len(self._secrets)} secret(s) redacted>)"
