"""Liveness and readiness checks (FR-09). Responses never include configuration."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..logging_config import log_event
from ..schemas import HealthOut, ReadyOut

router = APIRouter(tags=["health"])
logger = logging.getLogger("app.health")


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    """The API process is up. Does not touch the database."""
    return HealthOut(status="ok")


@router.get("/ready", response_model=ReadyOut, responses={503: {"model": ReadyOut}})
def ready(db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    """The API can reach PostgreSQL and read the video directory."""
    checks: dict[str, str] = {}
    try:
        db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001 - report any failure as not ready
        checks["database"] = "error"
        log_event(logger, "ready_check_failed", logging.ERROR, check="database", error=type(exc).__name__)

    root = settings.video_root
    if root.is_dir() and os.access(root, os.R_OK | os.X_OK):
        checks["media_storage"] = "ok"
    else:
        checks["media_storage"] = "error"
        log_event(logger, "ready_check_failed", logging.ERROR, check="media_storage")

    ok = all(v == "ok" for v in checks.values())
    body = ReadyOut(status="ok" if ok else "degraded", checks=checks)
    return JSONResponse(body.model_dump(), status_code=200 if ok else 503)
