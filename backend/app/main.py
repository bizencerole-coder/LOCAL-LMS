"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import get_settings
from .errors import install_error_handlers, internal_error_response, service_busy_response
from .logging_config import configure_logging, log_event, request_id_var
from .admin import install_admin
from .routers import auth, catalog, health, playback, progress

access_logger = logging.getLogger("app.access")
logger = logging.getLogger("app.errors")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_SWAGGER_DIR = Path(__file__).resolve().parent / "static" / "swagger"


class DbAdmission:
    """Pure ASGI gate: at most ``limit`` requests inside the app per worker.

    Sync endpoints run in a thread pool and hold a pooled database connection from
    authentication until the response has been sent. Without a gate, a burst larger
    than the pool fills every thread with requests waiting for a connection while the
    connection holders wait for a thread, and the worker stalls until Nginx times out.
    Requests that cannot be admitted within ``wait_seconds`` get 503 service_busy.

    This must wrap the whole ASGI call (not BaseHTTPMiddleware's call_next, which
    returns when the response starts, before the session is closed).
    """

    def __init__(self, app, limit: int, wait_seconds: float) -> None:
        self.app = app
        self.wait_seconds = wait_seconds
        self._slots = asyncio.Semaphore(limit)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope["path"] == "/health":
            await self.app(scope, receive, send)
            return
        try:
            async with asyncio.timeout(self.wait_seconds):
                await self._slots.acquire()
        except TimeoutError:
            log_event(logger, "admission_timeout", logging.WARNING, path=scope["path"])
            await service_busy_response()(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        finally:
            self._slots.release()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title="Campus LMS API",
        version=__version__,
        description="Local campus learning API (student app) and staff dashboard (/admin). Files are served by Nginx.",
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.enable_api_docs else None,
    )
    install_error_handlers(app)

    if settings.enable_api_docs:
        # Swagger UI with vendored assets, so /docs works on a LAN without internet.
        app.mount("/docs-assets", StaticFiles(directory=_SWAGGER_DIR), name="docs-assets")

        @app.get("/docs", include_in_schema=False)
        async def swagger_ui():
            return get_swagger_ui_html(
                openapi_url="/openapi.json",
                title=f"{app.title} - docs",
                swagger_js_url="/docs-assets/swagger-ui-bundle.js",
                swagger_css_url="/docs-assets/swagger-ui.css",
                swagger_favicon_url="/docs-assets/favicon-32x32.png",
            )

    # Inner middleware (added first): request admission gate.
    app.add_middleware(
        DbAdmission,
        limit=settings.db_admission_limit or (settings.db_pool_size + settings.db_max_overflow),
        wait_seconds=settings.db_admission_wait_seconds,
    )

    # Outer middleware: request IDs and the access log.
    @app.middleware("http")
    async def access_log(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = 500
        try:
            try:
                response = await call_next(request)
            except Exception:
                # Handled here rather than by Starlette's outer error middleware, so the
                # log line and the response keep this request's ID and the traceback is
                # logged once.
                logger.exception("unhandled_exception")
                response = internal_error_response()
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            # Path only: query strings are not logged.
            log_event(
                access_logger,
                "request",
                method=request.method,
                path=request.url.path,
                status=status,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
                client=request.client.host if request.client else "-",
                student_id=getattr(request.state, "student_id", "-"),
                staff_id=getattr(request.state, "staff_id", "-"),
            )
            request_id_var.reset(token)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(catalog.router)
    app.include_router(playback.router)
    app.include_router(progress.router)
    install_admin(app)

    @app.get("/", include_in_schema=False)
    async def root():
        # Staff typing the server address into a browser land on the dashboard.
        return RedirectResponse("/admin/", status_code=303)

    return app


app = create_app()
