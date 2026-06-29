"""CP3 — Production Workflow Wiring tests (Phase 8).

Verifies:
  3.1 WorkerKind enum values match config constants.
  3.2 WorkerRouter classifies documentation tasks correctly.
  3.3 WorkerRouter fails fast for unsupported kinds.
  3.4 validate_production_config fails fast when queen endpoint is missing.
  3.5 validate_production_config fails fast when local (worker) endpoint is missing.
  3.6 validate_production_config passes with both endpoints configured.
  3.7 build_production_workflow_services raises ConfigInvalid when no provider config.
  3.8 build_production_workflow_services raises NestNotFound when no .ant/ exists.
  3.9 Production composition assembles real DocumentationExecutionAdapter (no stub).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ant_orchestrator.config.constants import DOC_WORKER_KIND, TEST_WORKER_KIND
from ant_orchestrator.config.errors import ConfigInvalid
from ant_orchestrator.config.models import (
    ModelEndpointConfig,
    ModelsConfig,
    ProjectConfig,
    ResolvedConfig,
)
from ant_orchestrator.core.domain.enums import WorkerKind
from ant_orchestrator.workers.routing import WorkerKindUnsupported, WorkerRouter

_QUEEN = ModelEndpointConfig(provider="openai", model="gpt-4o-mini")
_LOCAL = ModelEndpointConfig(
    provider="ollama", model="qwen2.5-coder", base_url="http://localhost:11434"
)


def _config(
    *, queen: ModelEndpointConfig | None = None, local: ModelEndpointConfig | None = None
) -> ResolvedConfig:
    return ResolvedConfig(
        version=1,
        project=ProjectConfig(name="test"),
        models=ModelsConfig(queen=queen, local=local),
    )


# ---------------------------------------------------------------------------
# 3.1 WorkerKind enum
# ---------------------------------------------------------------------------


def test_worker_kind_documentation_matches_constant() -> None:
    assert WorkerKind.DOCUMENTATION.value == DOC_WORKER_KIND


def test_worker_kind_test_matches_constant() -> None:
    assert WorkerKind.TEST.value == TEST_WORKER_KIND


def test_worker_kind_parse_documentation() -> None:
    assert WorkerKind.parse("documentation") is WorkerKind.DOCUMENTATION


def test_worker_kind_parse_test() -> None:
    assert WorkerKind.parse("test") is WorkerKind.TEST


# ---------------------------------------------------------------------------
# 3.2 WorkerRouter classification
# ---------------------------------------------------------------------------


def test_worker_router_returns_documentation_by_default() -> None:
    from tests.support.workflow_factories import make_task

    router = WorkerRouter()
    task = make_task()
    assert router.classify(task) is WorkerKind.DOCUMENTATION


# ---------------------------------------------------------------------------
# 3.3 WorkerKindUnsupported
# ---------------------------------------------------------------------------


def test_worker_router_assert_supported_documentation_passes() -> None:
    router = WorkerRouter()
    router.assert_supported(WorkerKind.DOCUMENTATION)  # must not raise


def test_worker_router_assert_supported_test_raises() -> None:
    router = WorkerRouter()
    with pytest.raises(WorkerKindUnsupported):
        router.assert_supported(WorkerKind.TEST)


# ---------------------------------------------------------------------------
# 3.4 + 3.5 + 3.6  validate_production_config
# ---------------------------------------------------------------------------


def test_production_config_missing_queen_fails_fast() -> None:
    from ant_orchestrator.cli.composition_production import validate_production_config

    with pytest.raises(ConfigInvalid, match="queen"):
        validate_production_config(_config(local=_LOCAL))


def test_production_config_missing_worker_fails_fast() -> None:
    from ant_orchestrator.cli.composition_production import validate_production_config

    with pytest.raises(ConfigInvalid, match="local"):
        validate_production_config(_config(queen=_QUEEN))


def test_production_config_with_both_endpoints_validates() -> None:
    from ant_orchestrator.cli.composition_production import validate_production_config

    validate_production_config(_config(queen=_QUEEN, local=_LOCAL))  # must not raise


# ---------------------------------------------------------------------------
# 3.7  build_production_workflow_services — no config → ConfigInvalid
# ---------------------------------------------------------------------------


def test_production_services_no_provider_config_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ant run without provider config must fail-fast with ConfigInvalid (exit 2)."""
    from typer.testing import CliRunner

    from ant_orchestrator.cli.composition_production import build_production_workflow_services
    from ant_orchestrator.cli.main import app

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["init"], catch_exceptions=False)
    assert result.exit_code == 0, result.stdout

    with pytest.raises(ConfigInvalid):
        build_production_workflow_services(tmp_path)


# ---------------------------------------------------------------------------
# 3.8  build_production_workflow_services — no nest → NestNotFound
# ---------------------------------------------------------------------------


def test_production_services_no_nest_raises(tmp_path: Path) -> None:
    from ant_orchestrator.application.ports.workspace import NestNotFound
    from ant_orchestrator.cli.composition_production import build_production_workflow_services

    with pytest.raises(NestNotFound):
        build_production_workflow_services(tmp_path)


# ---------------------------------------------------------------------------
# 3.9  Production composition assembles real adapter (no DeterministicStubAdapter)
# ---------------------------------------------------------------------------


def test_production_composition_wires_real_documentation_adapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build_production_workflow_services must wire DocumentationExecutionAdapter, not stub.

    Uses a FakeLLMAdapter to satisfy the provider requirement without a live network.
    """
    from typer.testing import CliRunner

    from ant_orchestrator.cli.composition_production import build_production_workflow_services
    from ant_orchestrator.cli.main import app
    from ant_orchestrator.integration.execution_adapter import DocumentationExecutionAdapter
    from ant_orchestrator.workers.stub import DeterministicStubAdapter
    from tests.support.fake_llm import FakeLLMAdapter

    # Initialize a Nest
    monkeypatch.chdir(tmp_path)
    runner_cli = CliRunner()
    result = runner_cli.invoke(app, ["init"], catch_exceptions=False)
    assert result.exit_code == 0, result.stdout

    # Write minimal config with both queen + local endpoints
    config_content = (
        "version: 1\n"
        "models:\n"
        "  queen:\n"
        "    provider: openai\n"
        "    model: gpt-4o-mini\n"
        "  local:\n"
        "    provider: ollama\n"
        "    model: qwen2.5-coder\n"
        "    base_url: http://localhost:11434\n"
    )
    (tmp_path / ".ant" / "config.yaml").write_text(config_content, encoding="utf-8")

    # Bypass real LLM construction — substitute FakeLLMAdapter for local adapter
    fake_adapter = FakeLLMAdapter()
    monkeypatch.setattr(
        "ant_orchestrator.composition_production.build_llm_adapter",
        lambda *_a, **_kw: fake_adapter,
        raising=False,
    )
    # The import inside build_production_workflow_services uses a local import,
    # so patch the adapters.factory module directly.
    import ant_orchestrator.adapters.factory as _factory

    monkeypatch.setattr(_factory, "build_llm_adapter", lambda *_a, **_kw: fake_adapter)

    services = build_production_workflow_services(tmp_path)

    wf_runner = services.run_workflow._runner  # type: ignore[attr-defined]
    assert not isinstance(wf_runner._worker, DeterministicStubAdapter), (
        "DeterministicStubAdapter must not appear in production composition"
    )
    assert wf_runner._documentation_execution is not None
    assert isinstance(wf_runner._documentation_execution, DocumentationExecutionAdapter)
