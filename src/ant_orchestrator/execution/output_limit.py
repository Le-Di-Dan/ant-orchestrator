"""Output byte limiter — bounded drain, redact, truncate (CP3).

Drains a binary pipe keeping at most ``limit + safety_margin`` bytes for
redaction, then truncates to the hard limit. UTF-8 decode uses ``replace``
for deterministic handling of invalid sequences.

Does not spawn processes or perform I/O beyond the pipe passed to it.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Final

from ant_orchestrator.config.constants import (
    DRAIN_CHUNK_SIZE,
    OUTPUT_TRUNCATION_MARKER,
    REDACTION_SAFETY_MARGIN_BYTES,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.security.redaction.redactor import RedactionResult, Redactor

_CHUNK: Final = DRAIN_CHUNK_SIZE
_MARGIN: Final = REDACTION_SAFETY_MARGIN_BYTES


@dataclass(frozen=True, slots=True)
class OutputLimit:
    """Per-stream byte cap. Must be large enough for the truncation marker."""

    max_bytes: int

    def __post_init__(self) -> None:
        marker_len = len(OUTPUT_TRUNCATION_MARKER.encode("utf-8"))
        if self.max_bytes < marker_len + 1:
            raise InvariantViolation(
                f"OutputLimit.max_bytes ({self.max_bytes}) must exceed "
                f"truncation marker length ({marker_len})"
            )


@dataclass(frozen=True, slots=True)
class TruncatedOutput:
    """Sanitized output with truncation metadata."""

    text: str
    truncated: bool
    original_bytes: int


class OutputLimiter:
    """Drain, redact, then truncate a binary stream."""

    def __init__(self, limit: OutputLimit, redactor: Redactor) -> None:
        self._max = limit.max_bytes
        self._retention = limit.max_bytes + _MARGIN
        self._redactor = redactor
        self._marker = OUTPUT_TRUNCATION_MARKER

    def drain_and_process(self, pipe: io.RawIOBase | io.BufferedIOBase) -> TruncatedOutput:
        """Read all bytes from *pipe*, keeping a bounded buffer."""
        retained, total = self._drain(pipe)
        decoded = retained.decode("utf-8", errors="replace")
        result = self._redactor.redact(decoded)
        return self._truncate(result, total)

    def process_bytes(self, raw: bytes) -> TruncatedOutput:
        """Process already-collected raw bytes (for testing or pre-drained data)."""
        total = len(raw)
        kept = raw[: self._retention]
        decoded = kept.decode("utf-8", errors="replace")
        result = self._redactor.redact(decoded)
        return self._truncate(result, total)

    # ------------------------------------------------------------------

    def _drain(self, pipe: io.RawIOBase | io.BufferedIOBase) -> tuple[bytes, int]:
        buf = bytearray()
        total = 0
        while True:
            chunk = pipe.read(_CHUNK)
            if not chunk:
                break
            total += len(chunk)
            space = self._retention - len(buf)
            if space > 0:
                buf.extend(chunk[:space])
        return bytes(buf), total

    def _truncate(self, result: RedactionResult, total: int) -> TruncatedOutput:
        encoded = result.text.encode("utf-8")
        if len(encoded) <= self._max:
            return TruncatedOutput(result.text, truncated=total > self._max, original_bytes=total)
        cut = self._max - len(self._marker.encode("utf-8"))
        safe = encoded[:cut].decode("utf-8", errors="ignore")
        return TruncatedOutput(safe + self._marker, truncated=True, original_bytes=total)
