"""Active no-network enforcement for the self-test (Phase 8 CP6).

Patches the low-level socket connect primitives so any outbound connection attempt
raises immediately and is recorded. The self-test runs its deterministic scenario
inside this guard: if the code under test never touches the network the guard's
``attempts`` stays at zero (the ``security.no_network`` check passes); if anything
attempts a connection the guard surfaces it as a failure instead of silently
allowing a real network call.
"""

from __future__ import annotations

import socket
from types import TracebackType


class NetworkAccessAttempted(RuntimeError):
    """Raised when guarded code attempts an outbound network connection."""


class NetworkGuard:
    """Context manager that blocks and counts outbound socket connections."""

    def __init__(self) -> None:
        self.attempts = 0
        self._saved_connect: object | None = None
        self._saved_connect_ex: object | None = None

    def __enter__(self) -> NetworkGuard:
        self._saved_connect = socket.socket.connect
        self._saved_connect_ex = socket.socket.connect_ex

        def _blocked_connect(_self: socket.socket, _address: object) -> None:
            self.attempts += 1
            raise NetworkAccessAttempted("network access is forbidden during self-test")

        socket.socket.connect = _blocked_connect  # type: ignore[method-assign,assignment]
        socket.socket.connect_ex = _blocked_connect  # type: ignore[method-assign,assignment]
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        socket.socket.connect = self._saved_connect  # type: ignore[method-assign,assignment]
        socket.socket.connect_ex = self._saved_connect_ex  # type: ignore[method-assign,assignment]
