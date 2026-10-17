"""File uploads from the dashboard: PUT /admin/upload/{module_id}.

The browser sends the raw file as the request body (with progress events), so large
videos are streamed straight to disk: into VIDEO_ROOT/.uploads (ignored by the folder
sync), checked, then renamed into the module's folder, which is instant because it is
the same filesystem. No temporary copies in memory or /tmp.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from ..catalog_sync import display_name
from ..config import Settings, get_settings
from ..db import get_db
from ..fileinfo import ContentFileError, inspect_content_file
from ..logging_config import log_event
from ..media import content_type_for
from ..models import Content, ContentStatus, Module, StaffUser
from ..storage import (
    FILE_MODE,
    catalogue_lock,
    content_file_stem,
    ensure_dir,
    module_chain,
    module_dir,
    module_rel,
    unique_file_name,
    uploads_dir,
    write_sidecar,
)
from . import ops
from .auth import check_csrf, check_origin, current_staff

router = APIRouter(prefix="/admin", include_in_schema=False)
logger = logging.getLogger("app.admin.upload")
_WRITE_CHUNK = 4 * 1024 * 1024


class UploadError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"ok": False, "error": message}, status_code=status)


def _write(handle, digest, data: bytes) -> None:
    digest.update(data)
    handle.write(data)


def _finalize(
    db: Session,
    root: Path,
    module_id: uuid.UUID,
    temp: Path,
    original_name: str,
    title: str,
    description: str | None,
    publish: bool,
    checksum: str,
) -> dict:
    """Check the uploaded file, move it into the module folder and register it."""
    try:
        info = inspect_content_file(temp, checksum=checksum)
    except ContentFileError as exc:
        raise UploadError(400, f"{original_name}: {exc}".replace(str(temp), original_name)) from exc

    catalogue_lock(db)
    module = db.get(Module, module_id)
    if module is None:
        raise UploadError(404, "The module was deleted while the file was uploading.")
    batch, school_class, subject = module_chain(db, module)
    folder = module_dir(db, root, module)
    ensure_dir(folder)
    order = ops.next_content_order(db, module)
    title = ops.clean_name(title or display_name(Path(original_name).stem)[1] or "Untitled", "Title")
    name = unique_file_name(folder, content_file_stem(order, title), Path(original_name).suffix.lower())
    final = folder / name
    os.replace(temp, final)
    try:
        os.chmod(final, FILE_MODE)
    except OSError:
        pass
    try:
        status = ContentStatus.PUBLISHED if (publish and not info.problems) else ContentStatus.DRAFT
        content = Content(
            module_id=module.id,
            title=title,
            description=description,
            storage_key=f"{module_rel(batch, school_class, subject, module)}/{name}",
            sort_order=order,
            status=status.value,
            **info.metadata(),
        )
        db.add(content)
        db.flush()
        write_sidecar(final, title, description)
        db.commit()
    except Exception:
        db.rollback()
        final.unlink(missing_ok=True)
        final.with_suffix(".txt").unlink(missing_ok=True)
        raise
    return {
        "ok": True,
        "id": str(content.id),
        "title": content.title,
        "type": content.content_type,
        "status": content.status,
        "problems": info.problems,
        "url": f"/admin/contents/{content.id}",
    }


@router.put("/upload/{module_id}")
async def upload(
    module_id: uuid.UUID,
    request: Request,
    filename: str = Query(min_length=1, max_length=255),
    title: str = Query(default="", max_length=200),
    description: str = Query(default="", max_length=2000),
    publish: bool = False,
    staff: StaffUser = Depends(current_staff),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        check_origin(request)
        check_csrf(request, request.headers.get("x-csrf-token"))
    except Exception:
        return _error(403, "Your session has expired. Reload the page and try again.")

    original_name = Path(filename.replace("\\", "/")).name
    if content_type_for(original_name) is None:
        return _error(400, f"{original_name}: only MP4 videos, PDF notes and JPG/PNG/WebP images can be uploaded.")
    if await run_in_threadpool(db.get, Module, module_id) is None:
        return _error(404, "Module not found.")
    # Release the database connection while the file streams in.
    await run_in_threadpool(db.rollback)

    root = settings.video_root
    declared = request.headers.get("content-length")
    expected = int(declared) if declared and declared.isdigit() else None
    if expected is not None and expected > settings.upload_max_bytes:
        return _error(413, f"{original_name} is larger than the upload limit ({settings.upload_max_bytes // 1024**3} GB).")
    try:
        free = shutil.disk_usage(root).free
    except OSError:
        return _error(503, "The content folder is not available on the server.")
    if free - (expected or 0) < settings.upload_min_free_bytes:
        return _error(507, "The server's content disk is nearly full. Free some space first.")

    temp = await run_in_threadpool(lambda: uploads_dir(root) / f"{uuid.uuid4().hex}{Path(original_name).suffix.lower()}")
    digest = hashlib.sha256()
    received = 0
    try:
        handle = await run_in_threadpool(open, temp, "xb")
        try:
            buffer = bytearray()
            async for chunk in request.stream():
                received += len(chunk)
                if received > settings.upload_max_bytes:
                    raise UploadError(413, f"{original_name} is larger than the upload limit.")
                buffer += chunk
                if len(buffer) >= _WRITE_CHUNK:
                    await run_in_threadpool(_write, handle, digest, bytes(buffer))
                    buffer.clear()
            if buffer:
                await run_in_threadpool(_write, handle, digest, bytes(buffer))
        finally:
            await run_in_threadpool(handle.close)
        if expected is not None and received != expected:
            raise UploadError(400, f"{original_name} did not arrive completely. Try again.")
        if received == 0:
            raise UploadError(400, f"{original_name} is empty.")
        result = await run_in_threadpool(
            _finalize,
            db,
            root,
            module_id,
            temp,
            original_name,
            title.strip(),
            description.strip() or None,
            publish,
            digest.hexdigest(),
        )
    except ClientDisconnect:
        temp.unlink(missing_ok=True)
        log_event(logger, "upload_aborted", logging.WARNING, staff_id=staff.id, received=received)
        return _error(400, "The upload was interrupted.")
    except UploadError as exc:
        temp.unlink(missing_ok=True)
        return _error(exc.status, exc.message)
    except ops.FormError as exc:
        temp.unlink(missing_ok=True)
        return _error(400, exc.message)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    log_event(
        logger, "content_uploaded", staff_id=staff.id, content_id=result["id"], type=result["type"], bytes=received
    )
    return result
