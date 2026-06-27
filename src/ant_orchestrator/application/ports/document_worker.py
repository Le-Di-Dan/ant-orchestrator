"""Documentation Ant worker contracts (PHASE_5_PLAN CP1).

Three of the four Phase 5 data layers live here: the *semantic* task a worker is
asked to perform (``DocumentationTask``), the *minimal typed draft* a model may
return (``ModelCompositionDraft``), and the *system-assembled* execution report
(``WorkerExecutionReport``, AGENT_OPERATING_MODEL §12). The execution
scope/authority layer lives in ``execution_scope`` so this module carries no
permission/attempt/target-path authority.

Authority boundary (I2): a ``ModelCompositionDraft`` is authoritative ONLY for the
proposed content and the content-level metadata explicitly modelled below. It is
never authoritative for target, scope, files read/changed, commands, diff,
evidence, permission, or result — those are system-generated facts assembled into
``WorkerExecutionReport`` from audits.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from ant_orchestrator.application.ports.worker import MAX_WORKER_DETAIL_CHARS, WorkerOutcome
from ant_orchestrator.core.domain.errors import InvariantViolation

# Bounds (sanitized inputs only — never raw provider payloads).
MAX_PROPOSED_CONTENT_CHARS: Final = 200_000
MAX_REQUIRED_SECTIONS: Final = 64
MAX_REPORT_ITEMS: Final = 256


class DocumentOperation(Enum):
    """The single mutation a Documentation Ant task may perform (I8: one target)."""

    CREATE = "create"
    UPDATE = "update"


@dataclass(frozen=True, slots=True)
class DocumentationTask:
    """Semantic intent only — carries NO permission/scope/attempt authority (I4).

    ``target_document`` is a logical reference/purpose label, never an authoritative
    filesystem path: the authoritative target lives in ``ApprovedExecutionScope``.
    """

    logical_action_id: str
    operation: DocumentOperation
    target_document: str
    instruction_summary: str
    required_sections: tuple[str, ...]
    approved_inputs: tuple[str, ...] = ()
    expected_document_purpose: str = ""

    def __post_init__(self) -> None:
        if not self.logical_action_id:
            raise InvariantViolation("DocumentationTask.logical_action_id must be non-empty")
        if not self.target_document:
            raise InvariantViolation("DocumentationTask.target_document must be non-empty")
        if len(self.instruction_summary) > MAX_WORKER_DETAIL_CHARS:
            raise InvariantViolation("DocumentationTask.instruction_summary exceeds the bound")
        if len(self.required_sections) > MAX_REQUIRED_SECTIONS:
            raise InvariantViolation("DocumentationTask.required_sections exceeds the bound")
        if any(not section for section in self.required_sections):
            raise InvariantViolation("DocumentationTask.required_sections entries must be nonempty")


@dataclass(frozen=True, slots=True)
class ModelCompositionDraft:
    """Minimal typed draft returned by a model composer (I2).

    Authoritative ONLY for ``proposed_content`` and the optional content metadata
    (``summary``/``risks``/``next_steps``). Deliberately has NO field for files
    read/changed, commands, diff, evidence, permission, target, scope, or result —
    a model can therefore never *declare* an operational fact through this type.
    """

    proposed_content: str
    summary: str | None = None
    risks: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.proposed_content) > MAX_PROPOSED_CONTENT_CHARS:
            raise InvariantViolation("ModelCompositionDraft.proposed_content exceeds the bound")
        if self.summary is not None and len(self.summary) > MAX_WORKER_DETAIL_CHARS:
            raise InvariantViolation("ModelCompositionDraft.summary exceeds the bound")
        if len(self.risks) > MAX_REPORT_ITEMS or len(self.next_steps) > MAX_REPORT_ITEMS:
            raise InvariantViolation("ModelCompositionDraft list field exceeds the bound")


@dataclass(frozen=True, slots=True)
class WorkerExecutionReport:
    """System-assembled worker output (AGENT_OPERATING_MODEL §12).

    Every operational field is filled from system audits — never from a model
    draft (I2). ``risks``/``next_steps`` may incorporate *sanitized* draft metadata.
    """

    summary: str
    files_read: tuple[str, ...]
    files_changed: tuple[str, ...]
    commands: tuple[str, ...]
    result: WorkerOutcome
    evidence_refs: tuple[str, ...] = ()
    risks: tuple[str, ...] = ()
    next_steps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.summary) > MAX_WORKER_DETAIL_CHARS:
            raise InvariantViolation("WorkerExecutionReport.summary exceeds the bound")
        for name, items in (
            ("files_read", self.files_read),
            ("files_changed", self.files_changed),
            ("commands", self.commands),
            ("evidence_refs", self.evidence_refs),
            ("risks", self.risks),
            ("next_steps", self.next_steps),
        ):
            if len(items) > MAX_REPORT_ITEMS:
                raise InvariantViolation(f"WorkerExecutionReport.{name} exceeds the bound")
