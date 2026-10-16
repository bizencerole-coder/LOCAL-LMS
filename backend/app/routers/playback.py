"""Playback authorization (FR-04).

The API checks access and returns a short-lived signed Nginx URL. Video bytes
never pass through the API.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..access import visible_videos
from ..config import Settings, get_settings
from ..db import get_db
from ..deps import get_student
from ..errors import ApiError
from ..logging_config import log_event
from ..media import build_playback_url, is_readable_file, resolve_media_path
from ..models import Student, StudentVideoProgress, Video, utcnow
from ..schemas import PlaybackResponse

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


@router.post("/videos/{video_id}/playback", response_model=PlaybackResponse)
def authorize_playback(
    video_id: uuid.UUID,
    request: Request,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PlaybackResponse:
    video = db.scalar(visible_videos(student).where(Video.id == video_id))
    if video is None:
        # 404 rather than 403 so that IDs of other classes' or unpublished lessons
        # cannot be probed.
        log_event(logger, "playback_denied", logging.WARNING, student_id=student.id, video_id=video_id)
        raise ApiError(404, "not_found", "This lesson is not available.")

    if settings.check_media_file_on_playback and not is_readable_file(
        resolve_media_path(settings.video_root, video.storage_key)
    ):
        log_event(
            logger,
            "media_file_missing",
            logging.ERROR,
            video_id=video.id,
            storage_key=video.storage_key,
        )
        raise ApiError(
            503,
            "media_unavailable",
            "This lesson's video is not available right now. Please tell your teacher.",
        )

    expires = int(utcnow().timestamp()) + settings.playback_url_ttl_seconds
    base_url = settings.media_base_url or _base_url_from_request(request)
    url = build_playback_url(
        base_url=base_url,
        prefix=settings.media_url_prefix,
        storage_key=video.storage_key,
        sid=str(student.id),
        expires=expires,
        secret=settings.media_signing_secret,
    )

    progress = db.scalar(
        select(StudentVideoProgress).where(
            StudentVideoProgress.student_id == student.id,
            StudentVideoProgress.video_id == video.id,
        )
    )
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
