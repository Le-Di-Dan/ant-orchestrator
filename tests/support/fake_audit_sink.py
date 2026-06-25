"""FakeAuditSink — in-memory AuditSink test double (CP0).

Test-only: lives outside ``src/`` and is never imported by production code. It
records the events it is given (already-sanitized AuditEvents) so policy and
application code can be exercised without a real sink. Never persists to disk.
"""

from __future__ import annotations

from ant_orchestrator.application.ports.audit import AuditEvent


class FakeAuditSink:
    """Captures audit events in order for assertions in tests."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def write(self, event: AuditEvent) -> None:
        self.events.append(event)
