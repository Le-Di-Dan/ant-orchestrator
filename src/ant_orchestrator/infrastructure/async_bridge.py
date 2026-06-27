"""AsyncDependencyRunner — the single sync→async boundary (PHASE_5_PLAN CP5 / §9).

A synchronous worker (``WorkerExecutionPort`` is sync per ADR-0002) must invoke an
async dependency (the composer → ``LLMAdapter.complete``). This runner owns ONE
event-loop boundary with a timeout and clean cleanup. It never nests ``asyncio.run``
and never leaks a loop or a pending task.

Honesty contract:

- If called while an event loop is already running, it raises BEFORE creating the
  awaitable — so the underlying provider is never invoked (call count stays 0).
- A timeout cancels the in-flight coroutine and raises ``AsyncBridgeTimeoutError``;
  it does NOT auto-retry (the provider may have started — that ambiguity is the
  caller's ``IN_DOUBT`` to resolve).
- Any non-sanitized exception is wrapped so a raw provider exception/stack never
  escapes; already-sanitized ``AntError`` subclasses propagate unchanged.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from ant_orchestrator.config.constants import DEFAULT_TIMEOUT_SECONDS
from ant_orchestrator.errors import AntError

T = TypeVar("T")


class AsyncBridgeError(AntError):
    """Base class for sync→async bridge failures (sanitized; no raw cause)."""


class AsyncBridgeActiveLoopError(AsyncBridgeError):
    """The bridge was entered from a thread already running an event loop."""


class AsyncBridgeTimeoutError(AsyncBridgeError):
    """The awaited dependency did not complete within the timeout (no auto-retry)."""


class AsyncBridgeCancelledError(AsyncBridgeError):
    """The awaited dependency was cancelled."""


class AsyncDependencyRunner:
    """Runs an async dependency to completion from synchronous code, exactly once."""

    def __init__(self, *, default_timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        if default_timeout <= 0:
            raise AsyncBridgeError("default_timeout must be positive")
        self._default_timeout = default_timeout

    def run(self, factory: Callable[[], Awaitable[T]], *, timeout: float | None = None) -> T:
        """Await ``factory()`` on a dedicated loop with a timeout; fail closed otherwise.

        ``factory`` is invoked only AFTER the active-loop guard passes, so a rejected
        call never creates (let alone awaits) the underlying coroutine.
        """
        resolved = self._default_timeout if timeout is None else timeout
        if resolved <= 0:
            raise AsyncBridgeError("timeout must be positive")
        if self._loop_is_running():
            raise AsyncBridgeActiveLoopError("cannot bridge: an event loop is already running")

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(asyncio.wait_for(factory(), resolved))
        except TimeoutError:
            raise AsyncBridgeTimeoutError("async dependency timed out") from None
        except asyncio.CancelledError:
            raise AsyncBridgeCancelledError("async dependency was cancelled") from None
        except AntError:
            raise  # already sanitized — propagate unchanged
        except Exception:
            raise AsyncBridgeError("async dependency failed") from None
        finally:
            self._drain(loop)
            loop.close()

    @staticmethod
    def _loop_is_running() -> bool:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return False
        return True

    @staticmethod
    def _drain(loop: asyncio.AbstractEventLoop) -> None:
        pending = asyncio.all_tasks(loop)
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
