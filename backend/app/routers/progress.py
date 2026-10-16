"""Playback progress (FR-07). Identity comes from the session, never the body."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..access import visible_videos
from ..config import Settings, get_settings
from ..db import get_db
from ..deps import get_student
from ..errors import ApiError
from ..models import Student, StudentVideoProgress, Video, utcnow
from ..schemas import ProgressOut, ProgressUpdate

router = APIRouter(prefix="/api/v1", tags=["progress"])


def _visible_video_or_404(db: Session, student: Student, video_id: uuid.UUID) -> Video:
    video = db.scalar(visible_videos(student).where(Video.id == video_id))
    if video is None:
        raise ApiError(404, "not_found", "This lesson is not available.")
    return video


def _get_progress(db: Session, student_id: uuid.UUID, video_id: uuid.UUID):
    return db.scalar(
        select(StudentVideoProgress).where(
            StudentVideoProgress.student_id == student_id,
            StudentVideoProgress.video_id == video_id,
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


@router.get("/videos/{video_id}/progress", response_model=ProgressOut)
def get_progress(
    video_id: uuid.UUID,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
) -> ProgressOut:
    video = _visible_video_or_404(db, student, video_id)
    progress = _get_progress(db, student.id, video.id)
    if progress is None:
        return ProgressOut(
            video_id=video.id,
            position_seconds=0,
            duration_seconds=video.duration_seconds,
            is_completed=False,
            last_watched_at=None,
        )
    return ProgressOut.model_validate(progress, from_attributes=True)


@router.put("/videos/{video_id}/progress", response_model=ProgressOut)
def save_progress(
    video_id: uuid.UUID,
    body: ProgressUpdate,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ProgressOut:
    video = _visible_video_or_404(db, student, video_id)

    duration = video.duration_seconds or (
        int(body.duration_seconds) if body.duration_seconds else None
    )
    position = int(body.position_seconds)
    if duration:
        position = min(position, duration)
    reached_threshold = bool(
        settings.completion_threshold > 0
        and duration
        and position >= settings.completion_threshold * duration
    )
    completed = body.is_completed or reached_threshold
    now = utcnow()

    insert = _insert_for(db)
    stmt = insert(StudentVideoProgress).values(
        id=uuid.uuid4(),
        student_id=student.id,
        video_id=video.id,
        position_seconds=position,
        duration_seconds=duration,
        is_completed=completed,
        completed_at=now if completed else None,
        last_watched_at=now,
    )
    # Upsert on (student, video): retries never create duplicate rows (T-18), and a
    # lesson stays completed once completed.
    stmt = stmt.on_conflict_do_update(
        index_elements=[StudentVideoProgress.student_id, StudentVideoProgress.video_id],
        set_={
            "position_seconds": stmt.excluded.position_seconds,
            "duration_seconds": stmt.excluded.duration_seconds,
            "is_completed": or_(
                StudentVideoProgress.is_completed, stmt.excluded.is_completed
            ),
            "completed_at": func.coalesce(
                StudentVideoProgress.completed_at, stmt.excluded.completed_at
            ),
            "last_watched_at": stmt.excluded.last_watched_at,
        },
    )
    # RETURNING gives this request's own result. A separate read after the commit could
    # return a concurrent request's position, and would hold the connection longer.
    progress = db.scalars(
        stmt.returning(StudentVideoProgress), execution_options={"populate_existing": True}
    ).one()
    db.commit()
    return ProgressOut.model_validate(progress, from_attributes=True)
