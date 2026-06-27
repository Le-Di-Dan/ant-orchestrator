"""Pure recovery state machine for prepared mutations (PHASE_5_PLAN CP4 / D.4).

Given the journal status, the observed target state/digest, and a typed DB observation
(the real repository is wired only in CP6), decide the next recovery action. No action
requires the LLM: a crash at or after ``PREPARED`` is finalized from the durable
proposed artifact, never recomposed. External mutation (target digest matching neither
the previous nor the proposed digest) fails closed — never a blind overwrite or rollback.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ant_orchestrator.execution.mutation_artifacts import BeforeKind
from ant_orchestrator.execution.prepared_mutation import JournalStatus, MutationJournal


class TargetKind(Enum):
    """Observed presence of the target document on disk."""

    ABSENT = "absent"
    PRESENT = "present"


@dataclass(frozen=True, slots=True)
class TargetObservation:
    """The target's observed state — digest is set iff PRESENT."""

    kind: TargetKind
    digest: str | None = None


@dataclass(frozen=True, slots=True)
class DbObservation:
    """Typed DB observation (CP4 never reads the DB itself; CP6 supplies this)."""

    records_exist: bool = False


class RecoveryAction(Enum):
    """The action a caller must take to finalize (or refuse) a crashed mutation."""

    FRESH_EXECUTE = "fresh_execute"
    PUBLISH_THEN_VERIFY = "publish_then_verify"
    MARK_PUBLISHED = "mark_published"
    PERSIST_EXECUTION_RECORDS = "persist_execution_records"
    FINALIZE_COMPLETED = "finalize_completed"
    NOOP = "noop"
    FAIL_CONFLICT = "fail_conflict"
    FAIL_TARGET_MISMATCH = "fail_target_mismatch"


_FAIL_ACTIONS = frozenset({RecoveryAction.FAIL_CONFLICT, RecoveryAction.FAIL_TARGET_MISMATCH})


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    """A recovery action with a sanitized reason; ``requires_llm`` is always False."""

    action: RecoveryAction
    reason: str
    requires_llm: bool = False

    @property
    def is_failure(self) -> bool:
        return self.action in _FAIL_ACTIONS


class MutationRecovery:
    """Stateless recovery decider over (journal, target observation, DB observation)."""

    def decide(
        self,
        journal: MutationJournal | None,
        target: TargetObservation,
        db: DbObservation,
    ) -> RecoveryDecision:
        if journal is None:
            return RecoveryDecision(RecoveryAction.FRESH_EXECUTE, "no journal: start fresh")
        status = journal.status_enum
        if status is JournalStatus.PREPARED:
            return self._decide_prepared(journal, target)
        if status is JournalStatus.PUBLISHED:
            return self._decide_published(journal, target, db)
        return self._decide_completed(journal, target)

    def _decide_prepared(
        self, journal: MutationJournal, target: TargetObservation
    ) -> RecoveryDecision:
        if self._at_previous(journal, target):
            return RecoveryDecision(
                RecoveryAction.PUBLISH_THEN_VERIFY, "prepared: target still at previous state"
            )
        if self._at_proposed(journal, target):
            return RecoveryDecision(
                RecoveryAction.MARK_PUBLISHED, "prepared: target already holds proposed digest"
            )
        return RecoveryDecision(
            RecoveryAction.FAIL_CONFLICT, "prepared: external mutation / digest conflict"
        )

    def _decide_published(
        self, journal: MutationJournal, target: TargetObservation, db: DbObservation
    ) -> RecoveryDecision:
        if not self._at_proposed(journal, target):
            return RecoveryDecision(
                RecoveryAction.FAIL_TARGET_MISMATCH, "published: target digest mismatch"
            )
        if db.records_exist:
            return RecoveryDecision(
                RecoveryAction.FINALIZE_COMPLETED, "published: reconcile records then complete"
            )
        return RecoveryDecision(
            RecoveryAction.PERSIST_EXECUTION_RECORDS, "published: DB records missing"
        )

    def _decide_completed(
        self, journal: MutationJournal, target: TargetObservation
    ) -> RecoveryDecision:
        if self._at_proposed(journal, target):
            return RecoveryDecision(RecoveryAction.NOOP, "completed: idempotent no-op")
        return RecoveryDecision(
            RecoveryAction.FAIL_TARGET_MISMATCH, "completed: target digest mismatch"
        )

    @staticmethod
    def _at_previous(journal: MutationJournal, target: TargetObservation) -> bool:
        if journal.before_kind == BeforeKind.ABSENT.value:
            return target.kind is TargetKind.ABSENT
        return target.kind is TargetKind.PRESENT and target.digest == journal.previous_digest

    @staticmethod
    def _at_proposed(journal: MutationJournal, target: TargetObservation) -> bool:
        return target.kind is TargetKind.PRESENT and target.digest == journal.proposed_digest
