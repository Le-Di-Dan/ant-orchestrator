"""Minimal Typer CLI entry point for Ant-Orchestrator.

This module only wires up a root Typer application with a minimal callback so the
``ant`` console script is valid and ``ant --help`` works. It contains no business
logic; real commands are introduced in later phases.
"""

import typer

app = typer.Typer(help="Ant-Orchestrator CLI")


@app.callback()
def root() -> None:
    """Ant-Orchestrator CLI."""


def main() -> None:
    """Console-script entry point invoked by the ``ant`` command."""
    app()
