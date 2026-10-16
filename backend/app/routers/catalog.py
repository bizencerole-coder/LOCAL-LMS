"""Course catalogue (FR-02, FR-03): only content the student may access."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..access import visible_chapters, visible_subjects, visible_videos
from ..db import get_db
from ..deps import get_student
from ..errors import ApiError
from ..models import Chapter, Student, StudentVideoProgress, Subject, Video
from ..schemas import (
    ChapterOut,
    ProgressOut,
    RecentVideoOut,
    SubjectOut,
    VideoDetailOut,
    VideoOut,
)

router = APIRouter(prefix="/api/v1", tags=["catalogue"])


def progress_out(progress: StudentVideoProgress | None) -> ProgressOut | None:
    if progress is None:
        return None
    return ProgressOut(
        video_id=progress.video_id,
        position_seconds=progress.position_seconds,
        duration_seconds=progress.duration_seconds,
        is_completed=progress.is_completed,
        last_watched_at=progress.last_watched_at,
    )


def video_out(video: Video, progress: StudentVideoProgress | None) -> VideoOut:
    return VideoOut(
        id=video.id,
        chapter_id=video.chapter_id,
        title=video.title,
        description=video.description,
        duration_seconds=video.duration_seconds,
        sort_order=video.sort_order,
        progress=progress_out(progress),
    )


def _progress_by_video(
    db: Session, student: Student, video_ids: list[uuid.UUID]
) -> dict[uuid.UUID, StudentVideoProgress]:
    if not video_ids:
        return {}
    rows = db.scalars(
        select(StudentVideoProgress).where(
            StudentVideoProgress.student_id == student.id,
            StudentVideoProgress.video_id.in_(video_ids),
        )
    )
    return {row.video_id: row for row in rows}


@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(student: Student = Depends(get_student), db: Session = Depends(get_db)):
    subjects = db.scalars(visible_subjects(student).order_by(Subject.sort_order, Subject.name)).all()
    chapter_counts = dict(
        db.execute(
            visible_chapters(student, Chapter.subject_id, func.count(Chapter.id)).group_by(
                Chapter.subject_id
            )
        ).all()
    )
    video_counts = dict(
        db.execute(
            visible_videos(student, Chapter.subject_id, func.count(Video.id)).group_by(
                Chapter.subject_id
            )
        ).all()
    )
    return [
        SubjectOut(
            id=s.id,
            name=s.name,
            sort_order=s.sort_order,
            chapter_count=chapter_counts.get(s.id, 0),
            video_count=video_counts.get(s.id, 0),
        )
        for s in subjects
    ]


@router.get("/subjects/{subject_id}/chapters", response_model=list[ChapterOut])
def list_chapters(
    subject_id: uuid.UUID,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
):
    if db.scalar(visible_subjects(student, Subject.id).where(Subject.id == subject_id)) is None:
        raise ApiError(404, "not_found", "Subject not found.")
    chapters = db.scalars(
        visible_chapters(student)
        .where(Chapter.subject_id == subject_id)
        .order_by(Chapter.sort_order, Chapter.title)
    ).all()
    video_counts = dict(
        db.execute(
            visible_videos(student, Video.chapter_id, func.count(Video.id))
            .where(Chapter.subject_id == subject_id)
            .group_by(Video.chapter_id)
        ).all()
    )
    return [
        ChapterOut(
            id=c.id,
            subject_id=c.subject_id,
            title=c.title,
            description=c.description,
            sort_order=c.sort_order,
            video_count=video_counts.get(c.id, 0),
        )
        for c in chapters
    ]


@router.get("/chapters/{chapter_id}/videos", response_model=list[VideoOut])
def list_videos(
    chapter_id: uuid.UUID,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
):
    if db.scalar(visible_chapters(student, Chapter.id).where(Chapter.id == chapter_id)) is None:
        raise ApiError(404, "not_found", "Chapter not found.")
    videos = db.scalars(
        visible_videos(student)
        .where(Video.chapter_id == chapter_id)
        .order_by(Video.sort_order, Video.title)
    ).all()
    progress = _progress_by_video(db, student, [v.id for v in videos])
    return [video_out(v, progress.get(v.id)) for v in videos]


@router.get("/videos/{video_id}", response_model=VideoDetailOut)
def get_video(
    video_id: uuid.UUID,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
):
    row = db.execute(
        visible_videos(student, Video, Chapter.title, Subject.id, Subject.name).where(
            Video.id == video_id
        )
    ).first()
    if row is None:
        raise ApiError(404, "not_found", "Lesson not found.")
    video, chapter_title, subject_id, subject_name = row
    base = video_out(video, _progress_by_video(db, student, [video.id]).get(video.id))
    return VideoDetailOut(
        **base.model_dump(),
        chapter_title=chapter_title,
        subject_id=subject_id,
        subject_name=subject_name,
    )


@router.get("/me/recent", response_model=list[RecentVideoOut])
def recent_videos(
    limit: int = Query(default=10, ge=1, le=50),
    include_completed: bool = True,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
):
    """Recently watched lessons that are still available, newest first."""
    stmt = visible_videos(student, StudentVideoProgress, Video, Chapter.title, Subject.name).join(
        StudentVideoProgress,
        (StudentVideoProgress.video_id == Video.id)
        & (StudentVideoProgress.student_id == student.id),
    )
    if not include_completed:
        stmt = stmt.where(StudentVideoProgress.is_completed.is_(False))
    rows = db.execute(stmt.order_by(StudentVideoProgress.last_watched_at.desc()).limit(limit)).all()
    return [
        RecentVideoOut(video=video_out(video, progress), chapter_title=chapter, subject_name=subject)
        for progress, video, chapter, subject in rows
    ]
