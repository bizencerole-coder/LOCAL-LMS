"""Progress (FR-07). Identity comes from the session, never the body."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..access import visible_contents
from ..config import Settings, get_settings
from ..db import get_db
from ..deps import get_student
from ..errors import ApiError
from ..models import Content, ContentProgress, ContentType, Student, utcnow
from ..schemas import ContentProgressOut, ProgressOut, ProgressUpdate

router = APIRouter(prefix="/api/v1", tags=["progress"])


def _visible_or_404(db: Session, student: Student, content_id: uuid.UUID, video_only: bool = False) -> Content:
    stmt = visible_contents(student, content_type=ContentType.VIDEO.value if video_only else None)
    content = db.scalar(stmt.where(Content.id == content_id))
    if content is None:
        raise ApiError(404, "not_found", "This item is not available.")
    return content


def _get_progress(db: Session, student_id: uuid.UUID, content_id: uuid.UUID) -> ContentProgress | None:
    return db.scalar(
        select(ContentProgress).where(
            ContentProgress.student_id == student_id,
            ContentProgress.content_id == content_id,
        )
    )


def _insert_for(db: Session):
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    elif dialect == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:  # pragma: no cover
        raise RuntimeError(f"Unsupported database dialect for upsert: {dialect}")
    return insert


def upsert_progress(
    db: Session,
    student: Student,
    content: Content,
    *,
    position: int,
    duration: int | None,
    completed: bool,
) -> ContentProgress:
    """Insert or update one student's progress row; completion is permanent.

    The caller commits.
    """
    now = utcnow()
    insert = _insert_for(db)
    stmt = insert(ContentProgress).values(
        id=uuid.uuid4(),
        student_id=student.id,
        content_id=content.id,
        position_seconds=position,
        duration_seconds=duration,
        is_completed=completed,
        completed_at=now if completed else None,
        last_watched_at=now,
    )
    # Upsert on (student, content): retries never create duplicate rows (T-18), and an
    # item stays completed once completed.
    stmt = stmt.on_conflict_do_update(
        index_elements=[ContentProgress.student_id, ContentProgress.content_id],
        set_={
            "position_seconds": stmt.excluded.position_seconds,
            "duration_seconds": stmt.excluded.duration_seconds,
            "is_completed": or_(ContentProgress.is_completed, stmt.excluded.is_completed),
            "completed_at": func.coalesce(ContentProgress.completed_at, stmt.excluded.completed_at),
            "last_watched_at": stmt.excluded.last_watched_at,
        },
    )
    # RETURNING gives this request's own result. A separate read after the commit could
    # return a concurrent request's position, and would hold the connection longer.
    return db.scalars(
        stmt.returning(ContentProgress), execution_options={"populate_existing": True}
    ).one()


def _save(db: Session, student: Student, content: Content, body: ProgressUpdate, settings: Settings) -> ContentProgress:
    duration = content.duration_seconds or (int(body.duration_seconds) if body.duration_seconds else None)
    position = int(body.position_seconds)
    if duration:
        position = min(position, duration)
    reached_threshold = bool(
        settings.completion_threshold > 0
        and duration
        and position >= settings.completion_threshold * duration
    )
    progress = upsert_progress(
        db,
        student,
        content,
        position=position,
        duration=duration,
        completed=body.is_completed or reached_threshold,
    )
    db.commit()
    return progress


def _empty(content_id: uuid.UUID, duration: int | None) -> dict:
    return {
        "position_seconds": 0,
        "duration_seconds": duration,
        "is_completed": False,
        "last_watched_at": None,
        "content_id": content_id,
    }


@router.get("/contents/{content_id}/progress", response_model=ContentProgressOut)
def get_content_progress(
    content_id: uuid.UUID,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
) -> ContentProgressOut:
    content = _visible_or_404(db, student, content_id)
    progress = _get_progress(db, student.id, content.id)
    if progress is None:
        return ContentProgressOut(**_empty(content.id, content.duration_seconds))
    return ContentProgressOut.model_validate(progress, from_attributes=True)


@router.put("/contents/{content_id}/progress", response_model=ContentProgressOut)
def save_content_progress(
    content_id: uuid.UUID,
    body: ProgressUpdate,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ContentProgressOut:
    content = _visible_or_404(db, student, content_id)
    progress = _save(db, student, content, body, settings)
    return ContentProgressOut.model_validate(progress, from_attributes=True)


# --------------------------------------------------------------- legacy (app <= 1.0.x)


def _legacy(progress: ContentProgress) -> ProgressOut:
    return ProgressOut(
        video_id=progress.content_id,
        position_seconds=progress.position_seconds,
        duration_seconds=progress.duration_seconds,
        is_completed=progress.is_completed,
        last_watched_at=progress.last_watched_at,
    )


@router.get("/videos/{video_id}/progress", response_model=ProgressOut, deprecated=True)
def get_progress(
    video_id: uuid.UUID,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
) -> ProgressOut:
    video = _visible_or_404(db, student, video_id, video_only=True)
    progress = _get_progress(db, student.id, video.id)
    if progress is None:
        empty = _empty(video.id, video.duration_seconds)
        empty["video_id"] = empty.pop("content_id")
        return ProgressOut(**empty)
    return _legacy(progress)


@router.put("/videos/{video_id}/progress", response_model=ProgressOut, deprecated=True)
def save_progress(
    video_id: uuid.UUID,
    body: ProgressUpdate,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProgressOut:
    video = _visible_or_404(db, student, video_id, video_only=True)
    return _legacy(_save(db, student, video, body, settings))
