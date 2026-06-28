"""Deterministic identity chain for durable execution records (PHASE_5_PLAN CP6).

CP6 adds NO database column for idempotency; instead every durable record id is a
deterministic SHA-256 over the frozen identity chain
``run_id → logical_action_id → proposal_digest → stable_attempt_id``. Re-running the
same logical execution therefore computes the SAME id, so the database primary key is
the real idempotency authority: a retry collides on the PK (reuse/verify, never a
duplicate) and a different authority computes a different id (a structured conflict,
never a silent overwrite). The ids are opaque hex strings — never a raw secret.
"""

from __future__ import annotations

import hashlib
from typing import Final

from ant_orchestrator.config.constants import (
    DOC_WORKER_KIND,
    EVIDENCE_ENVELOPE_SCHEMA_VERSION,
    TEST_WORKER_KIND,
)

__all__ = [
    "energy_settlement_id",
    "evidence_id",
    "invocation_id",
    "terminal_handoff_id",
    "test_energy_id",
    "test_worker_run_id",
    "worker_run_id",
]

_SEP: Final = "\x00"


def _digest(domain: str, *parts: str) -> str:
    """SHA-256 hex over a domain-tagged, NUL-joined tuple (collision-isolated)."""
    seed = _SEP.join((domain, *parts))
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def invocation_id(
    run_id: str, attempt_id: str, logical_action_id: str, proposal_digest: str
) -> str:
    """Provider-invocation identity — IDENTICAL to the Documentation Ant's own derivation.

    The Ant seeds the composition receipt's ``invocation_id`` with the same NUL-joined
    chain (no domain tag), truncated to 32 hex chars, so the durable energy-settlement id
    derived here ties to the exact provider invocation the receipt recorded.
    """
    seed = _SEP.join((run_id, attempt_id, logical_action_id, proposal_digest))
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def worker_run_id(
    run_id: str,
    logical_action_id: str,
    proposal_digest: str,
    attempt_id: str,
    worker_kind: str = DOC_WORKER_KIND,
) -> str:
    """Deterministic ``WorkerRunId`` value bound to the full identity chain + worker kind."""
    return _digest(
        "worker_run", run_id, logical_action_id, proposal_digest, attempt_id, worker_kind
    )


def evidence_id(
    worker_run_id_value: str, schema_version: int = EVIDENCE_ENVELOPE_SCHEMA_VERSION
) -> str:
    """Deterministic ``EvidenceId`` for the single evidence row of a worker run."""
    return _digest("evidence", worker_run_id_value, str(schema_version))


def energy_settlement_id(invocation_id_value: str) -> str:
    """Deterministic ``EnergyUsageId`` keyed to the provider invocation (no re-charge)."""
    return _digest("energy_settlement", invocation_id_value)


def test_worker_run_id(run_id: str, logical_action_id: str, attempt_id: str) -> str:
    """Deterministic ``WorkerRunId`` for one Test Ant attempt (no proposal_digest)."""
    return _digest("worker_run", run_id, logical_action_id, "", attempt_id, TEST_WORKER_KIND)


def test_energy_id(run_id: str, attempt_id: str) -> str:
    """Deterministic ``EnergyUsageId`` for one Test Ant attempt (no double-charge on replay)."""
    return _digest("energy_test_run", run_id, attempt_id)


def terminal_handoff_id(run_id: str, final_outcome: str) -> str:
    """Deterministic ``HandoffId`` for one terminal workflow event (idempotent on replay)."""
    return _digest("terminal_handoff", run_id, final_outcome)
