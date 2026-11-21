"""Application error hierarchy and the uniform JSON error format.

Error response body (all endpoints)::

    {"error": {"code": "conflict", "message": "...", "details": {...}, "request_id": "..."}}

``code`` is a stable machine-readable identifier, ``message`` is German UI text.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError

from app.core.logging import request_id_var

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    message = "Ungültige Anfrage"

    def __init__(self, message: str | None = None, *, details: dict[str, Any] | None = None) -> None:
        self.message = message or self.message
        self.details = details or {}
        super().__init__(self.message)


class AuthenticationError(AppError):
    status_code = 401
    code = "unauthenticated"
    message = "Anmeldung erforderlich"


class AccountLockedError(AppError):
    status_code = 423
    code = "account_locked"
    message = "Konto vorübergehend gesperrt"


class PermissionDeniedError(AppError):
    status_code = 403
    code = "forbidden"
    message = "Keine Berechtigung für diese Aktion"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Datensatz nicht gefunden"


class ConflictError(AppError):
    """Raised on optimistic locking conflicts or unique constraint violations."""

    status_code = 409
    code = "conflict"
    message = "Der Datensatz wurde zwischenzeitlich geändert"


class NotAvailableError(AppError):
    """An optional component is not installed or not configured on this server."""

    status_code = 501
    code = "not_available"
    message = "Funktion auf diesem Server nicht verfügbar"


class ValidationFailedError(AppError):
    status_code = 422
    code = "validation_failed"
    message = "Eingaben ungültig"


def _body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "request_id": request_id_var.get(),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422, content=_body("validation_failed", "Eingaben ungültig", {"errors": errors})
        )

    @app.exception_handler(StaleDataError)
    async def _stale(_: Request, exc: StaleDataError) -> JSONResponse:
        # Concurrent update detected by the database-level version check.
        return JSONResponse(status_code=409, content=_body("conflict", ConflictError.message))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error")
        return JSONResponse(
            status_code=500, content=_body("internal_error", "Interner Serverfehler – bitte Fehler-ID melden")
        )
