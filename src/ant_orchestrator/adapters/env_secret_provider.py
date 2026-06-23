"""Environment-backed :class:`SecretProvider` (infrastructure adapter, CP2).

The only production place that reads secrets from ``os.environ``. It is stateless
(holds no secret), imports no provider SDK, and never logs names or values.
"""

from __future__ import annotations

import os


class EnvSecretProvider:
    """Reads secrets from the process environment.

    A missing variable, or one set to an empty string, resolves to ``None``. A
    non-empty value is returned unchanged.
    """

    def get(self, name: str) -> str | None:
        value = os.environ.get(name)
        if not value:
            return None
        return value
