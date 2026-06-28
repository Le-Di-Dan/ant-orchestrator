"""FastAPI application factory (Phase 7 CP7).

Usage via Uvicorn:
    uvicorn ant_orchestrator.api.main:create_default_app --factory --host 127.0.0.1 --port 8080

No module-level ``app = FastAPI()`` — each ``create_app(workspace)`` is independent.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from ant_orchestrator.api import errors as err_handlers
from ant_orchestrator.api.dependencies import build_api_services
from ant_orchestrator.api.routes import logs, tasks, worker_runs, workflow_runs
from ant_orchestrator.application.errors import WorkflowStateError
from ant_orchestrator.application.ports.database import DatabasePortError, RecordNotFound
from ant_orchestrator.core.domain.errors import DomainError


def create_app(workspace: Path) -> FastAPI:
    """Create a FastAPI app scoped to the given workspace directory."""
    app = FastAPI(title="Ant Orchestrator", docs_url=None, redoc_url=None)

    # Resolve services once per app instance; stored in app.state to avoid globals.
    app.state.services = build_api_services(workspace)

    # Register routers.
    app.include_router(tasks.router)
    app.include_router(workflow_runs.router)
    app.include_router(worker_runs.router)
    app.include_router(logs.router)

    # Register exception handlers (unified error envelope).
    app.add_exception_handler(RecordNotFound, err_handlers.handle_record_not_found)  # type: ignore[arg-type]
    app.add_exception_handler(WorkflowStateError, err_handlers.handle_workflow_state_error)  # type: ignore[arg-type]
    app.add_exception_handler(DomainError, err_handlers.handle_domain_error)  # type: ignore[arg-type]
    app.add_exception_handler(DatabasePortError, err_handlers.handle_database_port_error)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, err_handlers.handle_request_validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, err_handlers.handle_unexpected_error)

    return app


def create_default_app() -> FastAPI:
    """Zero-argument factory for Uvicorn ``--factory`` invocation."""
    return create_app(Path.cwd())
