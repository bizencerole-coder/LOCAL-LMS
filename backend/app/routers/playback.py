"""Opening content (videos, notes, images).

The API checks access and returns a short-lived signed Nginx URL. File bytes never
pass through the API. Opening notes or an image also records it as viewed.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..access import visible_contents
from ..config import Settings, get_settings
from ..db import get_db
from ..deps import get_student
from ..errors import ApiError
from ..logging_config import log_event
from ..media import build_playback_url, is_readable_file, resolve_media_path
from ..models import Content, ContentProgress, ContentType, Student, utcnow
from ..schemas import ContentAccessOut, PlaybackResponse
from .progress import upsert_progress

router = APIRouter(prefix="/api/v1", tags=["playback"])
logger = logging.getLogger("app.playback")

# host[:port] as a hostname, IPv4 address or bracketed IPv6 address.
_HOST_RE = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9-]+)*|\[[0-9A-Fa-f:.]+\])(:\d{1,5})?$")


def _base_url_from_request(request: Request) -> str:
    """Scheme and host the tablet used, when MEDIA_BASE_URL is not configured.

    The Host header is client-supplied, so it is validated rather than trusted: a
    missing or malformed value would otherwise make Starlette fall back to the
    internal API address, producing an unusable playback URL.
    """
    host = request.headers.get("host", "").strip()
    if not _HOST_RE.match(host):
        raise ApiError(
            400,
            "bad_request",
            "The request had no valid Host header. Set MEDIA_BASE_URL on the server.",
        )
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme) or "http"
    return f"{scheme}://{host}"


def _signed_url(content: Content, request: Request, settings: Settings, sid: str) -> tuple[str, int]:
    if settings.check_media_file_on_playback and not is_readable_file(
        resolve_media_path(settings.video_root, content.storage_key)
    ):
        log_event(
            logger,
            "media_file_missing",
            logging.ERROR,
            content_id=content.id,
            storage_key=content.storage_key,
        )
        raise ApiError(
            503,
            "media_unavailable",
            "This item's file is not available right now. Please tell your teacher.",
        )
    expires = int(utcnow().timestamp()) + settings.playback_url_ttl_seconds
    base_url = settings.media_base_url or _base_url_from_request(request)
    url = build_playback_url(
        base_url=base_url,
        prefix=settings.media_url_prefix,
        storage_key=content.storage_key,
        sid=sid,
        expires=expires,
        secret=settings.media_signing_secret,
    )
    return url, expires


def _progress(db: Session, student: Student, content: Content) -> ContentProgress | None:
    return db.scalar(
        select(ContentProgress).where(
            ContentProgress.student_id == student.id,
            ContentProgress.content_id == content.id,
        )
    )


@router.post("/contents/{content_id}/open", response_model=ContentAccessOut)
def open_content(
    content_id: uuid.UUID,
    request: Request,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ContentAccessOut:
    content = db.scalar(visible_contents(student).where(Content.id == content_id))
    if content is None:
        # 404 rather than 403 so that IDs of other classes' or unpublished items
        # cannot be probed.
        log_event(logger, "open_denied", logging.WARNING, student_id=student.id, content_id=content_id)
        raise ApiError(404, "not_found", "This item is not available.")

    url, expires = _signed_url(content, request, settings, sid=str(student.id))
    if content.content_type == ContentType.VIDEO.value:
        progress = _progress(db, student, content)
    else:
        # Notes and images count as done once opened; "My Learning" lists them.
        progress = upsert_progress(db, student, content, position=0, duration=None, completed=True)
        db.commit()
    log_event(logger, "content_opened", student_id=student.id, content_id=content.id, type=content.content_type)
    return ContentAccessOut(
        content_id=content.id,
        type=content.content_type,
        title=content.title,
        url=url,
        expires_at=datetime.fromtimestamp(expires, tz=UTC),
        mime_type=content.mime_type,
        duration_seconds=content.duration_seconds,
        file_size_bytes=content.file_size_bytes,
        resume_position_seconds=progress.position_seconds if progress else 0,
        is_completed=progress.is_completed if progress else False,
    )


@router.post("/videos/{video_id}/playback", response_model=PlaybackResponse, deprecated=True)
def authorize_playback(
    video_id: uuid.UUID,
    request: Request,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlaybackResponse:
    """Video playback for app versions before 1.1 (use /contents/{id}/open)."""
    video = db.scalar(
        visible_contents(student, content_type=ContentType.VIDEO.value).where(Content.id == video_id)
    )
    if video is None:
        log_event(logger, "playback_denied", logging.WARNING, student_id=student.id, video_id=video_id)
        raise ApiError(404, "not_found", "This lesson is not available.")

    url, expires = _signed_url(video, request, settings, sid=str(student.id))
    progress = _progress(db, student, video)
    log_event(logger, "playback_authorized", student_id=student.id, video_id=video.id)
    return PlaybackResponse(
        video_id=video.id,
        title=video.title,
        playback_url=url,
        expires_at=datetime.fromtimestamp(expires, tz=UTC),
        duration_seconds=video.duration_seconds,
        mime_type=video.mime_type,
        resume_position_seconds=progress.position_seconds if progress else 0,
        is_completed=progress.is_completed if progress else False,
    )
