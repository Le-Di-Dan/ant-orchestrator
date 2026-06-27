"""Test-only application-service subprocess driver for the CP8 restart E2E suite.

Runs as ``python -m tests.support.cp8_driver <command> --workspace <path> ...``.
It calls the *real* Phase 4 application services against the workspace's real
SQLite state DB and file checkpointer, optionally injecting a ``ScriptedStubAdapter``
and structured action-intent flags so non-default branches (retry/regroup/
escalation/significant-write/unsafe-command) become reachable. The process runs to
completion and exits — a later process re-opens all durable state from disk.

This is NOT production code: it adds no production command, flag or env switch.
Stdout carries exactly one JSON document; the exit code mirrors the CLI mapping.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.cli.exit_codes import exit_code_for
from ant_orchestrator.core.domain.enums import ActorSource
from ant_orchestrator.errors import AntError
from tests.support.cp8_driver_support import (
    build_scenario_services,
    seed_owned_resume,
    seed_running_run,
    set_run_version,
)


def _parse_outcomes(raw: str | None) -> list[WorkerOutcome]:
    if not raw:
        return []
    return [WorkerOutcome(token.strip()) for token in raw.split(",") if token.strip()]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cp8_driver")
    parser.add_argument("command")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--task-id", default=None)
    parser.add_argument("--title", default="cp8 task")
    parser.add_argument("--outcomes", default=None)
    parser.add_argument("--fallback", default=None)
    parser.add_argument("--base-retry-limit", type=int, default=2)
    parser.add_argument("--significant-write", action="store_true")
    parser.add_argument("--unsafe-command", action="store_true")
    parser.add_argument("--energy-approval", action="store_true")
    parser.add_argument("--reason", default="cp8 reject")
    parser.add_argument("--decision", default="rejected")
    parser.add_argument("--observed", action="store_true")
    parser.add_argument("--definition-version", type=int, default=None)
    return parser


def _emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload))


def _fail(command: str, exc: BaseException) -> NoReturn:
    _emit({"command": command, "error": {"type": type(exc).__name__, "message": str(exc)}})
    raise SystemExit(exit_code_for(exc))


def _outcome_payload(command: str, task_id: str, outcome: object) -> dict[str, object]:
    return {
        "command": command,
        "task_id": task_id,
        "status": getattr(outcome, "status", None),
        "workflow_run_id": getattr(outcome, "run_id", None) or None,
        "approval_id": getattr(outcome, "approval_id", None),
        "resume_operation_id": getattr(outcome, "resume_operation_id", None),
    }


def _energy_gate() -> dict[str, object]:
    """Demonstrate the ENERGY_BUDGET gate via the real Phase 3 EnforcementPolicy."""
    from ant_orchestrator.application.ports.energy import EnergyBudget
    from ant_orchestrator.energy.enforcement import EnforcementPolicy
    from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
    from tests.support.phase3_harness import make_plan

    policy = DecisionGatePolicy(EnforcementPolicy())
    result = policy.evaluate_energy_budget(make_plan(), EnergyBudget({}))
    return {
        "command": "energy-gate",
        "gate_type": result.gate_type.value,
        "outcome": result.outcome.value,
        "reason": result.reason.value,
    }


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    command: str = args.command
    workspace: Path = args.workspace

    if command == "energy-gate":
        _emit(_energy_gate())
        return 0

    services = build_scenario_services(
        workspace,
        outcomes=_parse_outcomes(args.outcomes),
        fallback=WorkerOutcome(args.fallback) if args.fallback else None,
        base_retry_limit=args.base_retry_limit,
        significant_write=args.significant_write,
        unsafe_command=args.unsafe_command,
        energy_approval=args.energy_approval,
        definition_version=(args.definition_version if args.definition_version is not None else 2),
    )

    try:
        if command == "create":
            task = services.create_task.create(title=args.title)
            _emit({"command": command, "task_id": task.id.value, "status": task.status.value})
            return 0
        if command == "seed-running":
            run_id = seed_running_run(
                services,
                task_id=args.task_id,
                observed=args.observed,
                definition_version=(
                    args.definition_version if args.definition_version is not None else 2
                ),
            )
            _emit({"command": command, "task_id": args.task_id, "workflow_run_id": run_id})
            return 0
        if command == "set-run-version":
            assert args.definition_version is not None
            run_id = set_run_version(
                services, task_id=args.task_id, definition_version=args.definition_version
            )
            _emit({"command": command, "task_id": args.task_id, "workflow_run_id": run_id})
            return 0
        if command == "seed-owned-resume":
            op_id = seed_owned_resume(services, task_id=args.task_id, decision=args.decision)
            _emit({"command": command, "task_id": args.task_id, "resume_operation_id": op_id})
            return 0
        if command == "schema-mismatch":
            return _run_schema_mismatch(services, args.task_id)
        if command == "definition-mismatch":
            services.runner.check_definition_version(99)
            _emit({"command": command, "status": "no_mismatch"})
            return 0

        outcome = _dispatch_workflow(services, command, args)
        _emit(_outcome_payload(command, args.task_id, outcome))
        return 0
    except AntError as exc:
        _fail(command, exc)


def _run_schema_mismatch(services: object, task_id: str) -> int:
    """Invoke with a tampered graph-state schema version → fail closed."""
    runner = services.runner  # type: ignore[attr-defined]
    state = runner.build_initial_state(
        task_id=task_id, workflow_run_id="bad-schema-run", base_retry_limit=2
    )
    state["graph_state_schema_version"] = 999
    runner.invoke(state, thread_id="bad-schema-thread")
    _emit({"command": "schema-mismatch", "status": "no_mismatch"})
    return 0


def _dispatch_workflow(services: object, command: str, args: argparse.Namespace) -> object:
    svc = services  # narrow alias
    if command == "run":
        return svc.run_workflow.execute(args.task_id)  # type: ignore[attr-defined]
    if command in ("crash-interrupt", "crash-end"):
        return svc.crash_run_workflow.execute(args.task_id)  # type: ignore[attr-defined]
    if command == "approve":
        return svc.resolve_approval.approve(  # type: ignore[attr-defined]
            args.task_id, actor_source=ActorSource.LOCAL_CLI
        )
    if command == "reject":
        return svc.resolve_approval.reject(  # type: ignore[attr-defined]
            args.task_id, reason=args.reason, actor_source=ActorSource.LOCAL_CLI
        )
    if command == "cancel":
        return svc.cancel_task.cancel(args.task_id)  # type: ignore[attr-defined]
    raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
