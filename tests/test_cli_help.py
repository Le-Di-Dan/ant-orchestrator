"""CLI smoke test: ``ant --help`` exits 0 and prints usage via the root callback."""

from typer.testing import CliRunner

from ant_orchestrator.cli.main import app

runner = CliRunner()


def test_cli_help_exits_zero_with_usage() -> None:
    """Invoking ``--help`` returns exit code 0 and shows the Usage section."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output
