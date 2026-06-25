"""Pre/post-side-effect audit event writer for local execution (CP8).

Extracted from EnergyManager to keep that facade under the 350-line limit.
"""

from __future__ import annotations

from ant_orchestrator.application.ports.audit import (
    AuditEvent,
    AuditEventType,
    AuditSink,
    CorrelationId,
)
from ant_orchestrator.application.ports.energy import (
    EnergyActionPlan,
    EnergyActionResult,
    EnergyDecision,
)
from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.energy.enforcement import EnforcementDecision
from ant_orchestrator.energy.reservation import EnergyReservation


class LocalAuditWriter:
    """Writes 3 pre-side-effect and 1 post-side-effect audit events."""

    def __init__(self, audit_sink: AuditSink, clock: Clock) -> None:
        self._audit = audit_sink
        self._clock = clock

    def pre_execute(
        self,
        plan: EnergyActionPlan,
        cid: CorrelationId,
        reservation: EnergyReservation,
    ) -> bool:
        """Write ROUTING_DECISION, ENERGY_RESERVATION, ENERGY_ENFORCEMENT events.

        Returns False if any write fails (caller must release reservation).
        """
        try:
            self._audit.write(
                AuditEvent(
                    event_type=AuditEventType.ROUTING_DECISION,
                    correlation_id=cid,
                    created_at=self._clock.now(),
                    detail={
                        "task_id": plan.task_id.value,
                        "action_kind": plan.action_kind.value,
                        "decision": EnergyDecision.ROUTE_LOCAL.value,
                    },
                    decision=PolicyDecision.ALLOW,
                )
            )
            self._audit.write(
                AuditEvent(
                    event_type=AuditEventType.ENERGY_RESERVATION,
                    correlation_id=cid,
                    created_at=self._clock.now(),
                    detail={
                        "reservation_id": reservation.id,
                        "task_id": plan.task_id.value,
                        "resources": str({k.value: v for k, v in reservation.amounts.items()}),
                    },
                    decision=PolicyDecision.ALLOW,
                )
            )
            self._audit.write(
                AuditEvent(
                    event_type=AuditEventType.ENERGY_ENFORCEMENT,
                    correlation_id=cid,
                    created_at=self._clock.now(),
                    detail={
                        "task_id": plan.task_id.value,
                        "enforcement": "allow",
                        "reservation_id": reservation.id,
                    },
                    decision=PolicyDecision.ALLOW,
                )
            )
        except Exception:
            return False
        return True

    def post_execute(
        self,
        plan: EnergyActionPlan,
        cid: CorrelationId,
        reservation: EnergyReservation,
        action_result: EnergyActionResult,
        enforcement: EnforcementDecision,
    ) -> bool:
        """Write post-side-effect ENERGY_ENFORCEMENT event.

        Returns False if write fails.
        """
        try:
            self._audit.write(
                AuditEvent(
                    event_type=AuditEventType.ENERGY_ENFORCEMENT,
                    correlation_id=cid,
                    created_at=self._clock.now(),
                    detail={
                        "task_id": plan.task_id.value,
                        "reservation_id": reservation.id,
                        "post_decision": enforcement.decision.value,
                        "actual": str({k.value: v for k, v in action_result.actual.items()}),
                    },
                    decision=PolicyDecision.ALLOW
                    if enforcement.decision is EnergyDecision.ALLOW
                    else PolicyDecision.DENY,
                )
            )
        except Exception:
            return False
        return True
