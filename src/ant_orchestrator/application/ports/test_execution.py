"""Graph-facing Test Ant execution port and outcome (PHASE_6_PLAN CP1, §D.3/§E/§F).

Mirrors ``documentation_execution.py``: the workflow graph depends only on this port and
on a compact, JSON-safe outcome — never on the Test Ant, the isolation backend, or
persistence. The pure :func:`worker_outcome_for` mapping turns a recovery disposition
into the workflow-facing :class:`WorkerOutcome`; it is exhaustive over dispositions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Protocol, runtime_checkable

from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    TestReasonCode,
)

# Recovery disposition → workflow-facing worker outcome. ``TERMINAL_CANCELLED`` is absent
# on purpose: cancellation is handled out-of-band by the workflow (TaskStatus.CANCELLED),
# never as a worker failure outcome — see :func:`worker_outcome_for`.
_DISPOSITION_OUTCOME: dict[RecoveryDisposition, WorkerOutcome] = {
    RecoveryDisposition.RETRY: WorkerOutcome.RETRYABLE_FAILURE,
    RecoveryDisposition.REGROUP_REQUIRED: WorkerOutcome.REVIEW_REGROUP,
    RecoveryDisposition.ESCALATE: WorkerOutcome.ESCALATION,
    RecoveryDisposition.TERMINAL_FAILED: WorkerOutcome.PERMANENT_FAILURE,
}


def worker_outcome_for(disposition: RecoveryDisposition) -> WorkerOutcome:
    """Map a failure ``disposition`` to its workflow-facing :class:`WorkerOutcome`.

    Exhaustive over the failure dispositions. ``TERMINAL_CANCELLED`` raises: cancellation
    is never routed as retry, regroup, escalate or failure — it is a terminal-cancelled
    state the workflow owns directly.
    """
    try:
        return _DISPOSITION_OUTCOME[disposition]
    except KeyError as exc:
        raise InvariantViolation(
            f"disposition {disposition.value} is not a worker failure outcome"
        ) from exc


@dataclass(frozen=True, slots=True)
class TestExecutionOutcome:
    """Compact, JSON-safe result of a durable Test Ant execution (graph-facing).

    Carries no raw output/exception/secret/host path — only a bounded outcome, the
    classification facets needed for routing, the stable attempt id and sanitized
    evidence references. On SUCCESS the failure facets are ``None``; on any non-success
    outcome they are required (consistency invariant). ``provider_invoked`` is always
    ``False``: the Test Ant never calls a model.
    """

    __test__ = False  # domain term; not a pytest test class

    outcome: WorkerOutcome
    attempt_ref: str
    disposition: RecoveryDisposition | None = None
    reason_code: TestReasonCode | None = None
    category: FailureCategory | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    provider_invoked: bool = False

    def __post_init__(self) -> None:
        if not self.attempt_ref:
            raise InvariantViolation("TestExecutionOutcome.attempt_ref must be non-empty")
        if self.provider_invoked:
            raise InvariantViolation("Test Ant never invokes a provider")
        if self.outcome is WorkerOutcome.SUCCESS:
            if self.disposition is not None or self.reason_code is not None:
                raise InvariantViolation("SUCCESS outcome must not carry failure facets")
        else:
            if self.disposition is None or self.reason_code is None or self.category is None:
                raise InvariantViolation("non-success outcome requires classification facets")

    def to_state_dict(self) -> dict[str, object]:
        """Render as a JSON-safe dict the workflow can fold into its state."""
        return {
            "outcome": self.outcome.value,
            "attempt_ref": self.attempt_ref,
            "disposition": self.disposition.value if self.disposition else None,
            "reason_code": self.reason_code.value if self.reason_code else None,
            "category": self.category.value if self.category else None,
            "evidence_refs": list(self.evidence_refs),
            "provider_invoked": self.provider_invoked,
        }


@runtime_checkable
class TestExecutionPort(Protocol):
    """Run one durable, read-only Test Ant execution for an approved attempt."""

    __test__: ClassVar[bool] = False  # domain term; not a pytest test class

    def execute(self, *, task_id: str, run_id: str, attempt_ref: str) -> TestExecutionOutcome:
        """Execute (or idempotently recover) the bound test action."""
        ...
