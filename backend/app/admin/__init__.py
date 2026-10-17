"""Staff web dashboard (/admin): content tree, uploads, students, staff, folder sync."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from urllib.parse import quote

from ..errors import internal_error_response
from ..logging_config import log_event
from .auth import Forbidden, LoginRequired
from .upload import router as upload_router
from .views import router as views_router
from .web import PERMISSION_HELP, FormError, NotFound, back, redirect, render

STATIC_DIR = Path(__file__).resolve().parent / "static"
logger = logging.getLogger("app.admin")


def _wants_json(request: Request) -> bool:
    return request.url.path.startswith("/admin/upload/") or "application/json" in request.headers.get("accept", "")


def install_admin(app: FastAPI) -> None:
    app.mount("/admin/static", StaticFiles(directory=STATIC_DIR), name="admin-static")
    app.include_router(upload_router)
    app.include_router(views_router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "Please sign in again."}, status_code=401)
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        if request.method != "GET":
            target = "/admin/"
        return RedirectResponse(f"/admin/login?next={quote(target, safe='/')}", status_code=303)

    @app.exception_handler(Forbidden)
    async def _forbidden(request: Request, exc: Forbidden):
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": exc.message}, status_code=403)
        return render(request, "error.html", {"title": "Not allowed", "message": exc.message}, status_code=403)

    @app.exception_handler(NotFound)
    async def _not_found(request: Request, exc: NotFound):
        return render(
            request,
            "error.html",
            {"title": "Not found", "message": f"This {exc.what} does not exist (it may have been deleted)."},
            status_code=404,
        )

    @app.exception_handler(FormError)
    async def _form_error(request: Request, exc: FormError):
        return redirect(back(request), exc.message, "error")

    @app.exception_handler(PermissionError)
    async def _no_write_access(request: Request, exc: PermissionError):
        # Raised when the API may not write in the content folder: a setup problem, not a bug.
        log_event(logger, "content_folder_not_writable", logging.ERROR, path=request.url.path, error=str(exc))
        message = PERMISSION_HELP
        if not request.url.path.startswith("/admin"):
            return internal_error_response()
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": message}, status_code=500)
        return render(request, "error.html", {"title": "Cannot write to the content folder", "message": message},
                      status_code=500)
