"""Phase 8 CP6 — ``antctl self-test`` command (thin adapter).

Runs the isolated deterministic self-test, renders the report (human or JSON) and
maps the overall result to an exit code: 0 when no check FAILed, 1 otherwise.
WARN/SKIP never fail the command. The deterministic verification lives entirely in
:class:`SelfTestRunner`; this module only parses options and renders output.
"""

from __future__ import annotations

import typer

from ant_orchestrator.cli import json_contract
from ant_orchestrator.cli.exit_codes import EXIT_OK, EXIT_UNEXPECTED
from ant_orchestrator.cli.self_test_runner import SelfTestRunner
from ant_orchestrator.cli.self_test_view import render_human, render_json

_JSON_OPTION = typer.Option(
    False, "--json", help="Emit a single JSON document on stdout (no ANSI)."
)
_KEEP_OPTION = typer.Option(
    False,
    "--keep-workspace",
    help="Keep the temporary workspace and print its path (debug only).",
)


def self_test(
    json_output: bool = _JSON_OPTION,
    keep_workspace: bool = _KEEP_OPTION,
) -> None:
    """Verify the installation end-to-end in an isolated, offline workspace."""
    report = SelfTestRunner(keep_workspace=keep_workspace).run()
    if json_output:
        typer.echo(json_contract.dumps(render_json(report)))
    else:
        for line in render_human(report):
            typer.echo(line)
    raise typer.Exit(EXIT_UNEXPECTED if report.has_failure else EXIT_OK)


def register(app: typer.Typer) -> None:
    """Attach the self-test command to the root Typer application."""
    app.command("self-test")(self_test)
