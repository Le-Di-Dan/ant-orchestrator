"""Unified error handlers for the FastAPI surface (Phase 7 CP7).

Maps domain/application errors to canonical JSON error responses.
No raw exceptions, tracebacks, paths, or secrets may appear in responses.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ant_orchestrator.application.errors import WorkflowStateError
from ant_orchestrator.application.ports.database import DatabasePortError, RecordNotFound
from ant_orchestrator.core.domain.errors import DomainError


def _error_body(error_type: str, message: str) -> dict[str, object]:
    return {"error": {"type": error_type, "message": message}}


async def handle_record_not_found(request: Request, exc: RecordNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content=_error_body("not_found", str(exc)))


async def handle_workflow_state_error(request: Request, exc: WorkflowStateError) -> JSONResponse:
    return JSONResponse(status_code=422, content=_error_body("workflow_state_error", str(exc)))


async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=422, content=_error_body("domain_error", str(exc)))


async def handle_database_port_error(request: Request, exc: DatabasePortError) -> JSONResponse:
    return JSONResponse(status_code=503, content=_error_body("storage_unavailable", str(exc)))


async def handle_request_validation_error(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    msg = "; ".join(
        f"{'.'.join(str(loc) for loc in err['loc'])}: {err['msg']}" for err in exc.errors()
    )
    return JSONResponse(status_code=422, content=_error_body("validation_error", msg))


async def handle_pydantic_validation_error(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=_error_body("validation_error", str(exc.error_count())),
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=_error_body("internal_error", "An unexpected error occurred."),
    )
