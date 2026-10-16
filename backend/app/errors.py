"""Consistent JSON error responses: ``{"error": {"code", "message"}, "request_id"}``."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DataError
from sqlalchemy.exc import TimeoutError as SATimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging_config import log_event, request_id_var

logger = logging.getLogger("app.errors")

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "too_many_requests",
    503: "service_unavailable",
}


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers


def unauthorized(message: str = "Please sign in again.") -> ApiError:
    return ApiError(401, "unauthorized", message, headers={"WWW-Authenticate": "Bearer"})


def _body(code: str, message: str, **extra: object) -> dict:
    return {"error": {"code": code, "message": message, **extra}, "request_id": request_id_var.get()}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            _body(exc.code, exc.message), status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "error")
        message = exc.detail if isinstance(exc.detail, str) else code
        return JSONResponse(
            _body(code, message), status_code=exc.status_code, headers=getattr(exc, "headers", None)
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"location": ".".join(str(p) for p in err.get("loc", ())), "message": err.get("msg")}
            for err in exc.errors()
        ]
        return JSONResponse(
            _body("validation_error", "The request was not valid.", fields=fields),
            status_code=422,
        )

    @app.exception_handler(DataError)
    async def _data_error(_: Request, exc: DataError) -> JSONResponse:
        # Input the database cannot store (e.g. NUL characters, out-of-range numbers).
        # SQL parameters are not logged (engine uses hide_parameters).
        log_event(logger, "database_rejected_input", logging.WARNING, error=type(exc.orig).__name__)
        return JSONResponse(
            _body("bad_request", "The request contained a value the server cannot store."),
            status_code=400,
        )

    @app.exception_handler(SATimeoutError)
    async def _pool_timeout(_: Request, exc: SATimeoutError) -> JSONResponse:
        log_event(logger, "db_pool_exhausted", logging.WARNING)
        return service_busy_response()

    # Other unhandled exceptions are caught by the access-log middleware in main.py,
    # which logs them with the request ID and returns internal_error_response().


def internal_error_response() -> JSONResponse:
    return JSONResponse(
        _body("internal_error", "Something went wrong on the server."), status_code=500
    )


def service_busy_response() -> JSONResponse:
    """503 for transient overload; clients (and the app's progress saver) retry later."""
    return JSONResponse(
        _body("service_busy", "The campus server is busy. Please try again in a moment."),
        status_code=503,
        headers={"Retry-After": "2"},
    )
