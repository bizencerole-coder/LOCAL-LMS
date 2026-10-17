"""Course catalogue: only content the student may access.

Current app: subjects -> modules -> contents (videos, notes, images).
Legacy app (<= 1.0.x): subjects -> chapters -> videos, served from the same tables with
only video content.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ..access import visible_contents, visible_modules, visible_subjects
from ..db import get_db
from ..deps import get_student
from ..errors import ApiError
from ..models import Content, ContentProgress, ContentType, Module, Student, Subject
from ..schemas import (
    ChapterOut,
    ContentDetailOut,
    ContentOut,
    ContentProgressOut,
    ContinueItemOut,
    ModuleOut,
    ProgressOut,
    RecentVideoOut,
    SubjectOut,
    VideoDetailOut,
    VideoOut,
)

router = APIRouter(prefix="/api/v1", tags=["catalogue"])

_VIDEO = ContentType.VIDEO.value


def _type_counts(*group_by):
    """Columns: group keys, then total / video / pdf / image counts."""
    return (
        *group_by,
        func.count(Content.id),
        func.sum(case((Content.content_type == ContentType.VIDEO.value, 1), else_=0)),
        func.sum(case((Content.content_type == ContentType.PDF.value, 1), else_=0)),
        func.sum(case((Content.content_type == ContentType.IMAGE.value, 1), else_=0)),
    )


def _counts_by(db: Session, stmt) -> dict[uuid.UUID, tuple[int, int, int, int]]:
    return {
        row[0]: (int(row[1] or 0), int(row[2] or 0), int(row[3] or 0), int(row[4] or 0))
        for row in db.execute(stmt).all()
    }


def _completed_by(db: Session, student: Student, group_column, *conditions) -> dict[uuid.UUID, int]:
    """{group id: number of visible items this student has completed}."""
    stmt = (
        visible_contents(student, group_column, func.count(Content.id))
        .join(
            ContentProgress,
            (ContentProgress.content_id == Content.id) & (ContentProgress.student_id == student.id),
        )
        .where(ContentProgress.is_completed.is_(True), *conditions)
        .group_by(group_column)
    )
    return {row[0]: int(row[1]) for row in db.execute(stmt).all()}


def content_progress_out(progress: ContentProgress | None) -> ContentProgressOut | None:
    if progress is None:
        return None
    return ContentProgressOut(
        content_id=progress.content_id,
        position_seconds=progress.position_seconds,
        duration_seconds=progress.duration_seconds,
        is_completed=progress.is_completed,
        last_watched_at=progress.last_watched_at,
    )


def content_out(content: Content, progress: ContentProgress | None) -> ContentOut:
    return ContentOut(
        id=content.id,
        module_id=content.module_id,
        type=content.content_type,
        title=content.title,
        description=content.description,
        sort_order=content.sort_order,
        duration_seconds=content.duration_seconds,
        file_size_bytes=content.file_size_bytes,
        progress=content_progress_out(progress),
    )


def progress_by_content(
    db: Session, student: Student, content_ids: list[uuid.UUID]
) -> dict[uuid.UUID, ContentProgress]:
    if not content_ids:
        return {}
    rows = db.scalars(
        select(ContentProgress).where(
            ContentProgress.student_id == student.id,
            ContentProgress.content_id.in_(content_ids),
        )
    )
    return {row.content_id: row for row in rows}


@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(student: Student = Depends(get_student), db: Session = Depends(get_db)):
    subjects = db.scalars(visible_subjects(student).order_by(Subject.sort_order, Subject.name)).all()
    module_counts = dict(
        db.execute(
            visible_modules(student, Module.subject_id, func.count(Module.id)).group_by(
                Module.subject_id
            )
        ).all()
    )
    counts = _counts_by(
        db, visible_contents(student, *_type_counts(Module.subject_id)).group_by(Module.subject_id)
    )
    completed = _completed_by(db, student, Module.subject_id)
    out = []
    for s in subjects:
        total, videos, notes, images = counts.get(s.id, (0, 0, 0, 0))
        modules = module_counts.get(s.id, 0)
        out.append(
            SubjectOut(
                id=s.id,
                name=s.name,
                description=s.description,
                sort_order=s.sort_order,
                module_count=modules,
                content_count=total,
                video_count=videos,
                notes_count=notes,
                image_count=images,
                completed_count=completed.get(s.id, 0),
                chapter_count=modules,
            )
        )
    return out


def _visible_subject_or_404(db: Session, student: Student, subject_id: uuid.UUID) -> None:
    if db.scalar(visible_subjects(student, Subject.id).where(Subject.id == subject_id)) is None:
        raise ApiError(404, "not_found", "Subject not found.")


def _visible_module_or_404(db: Session, student: Student, module_id: uuid.UUID) -> None:
    if db.scalar(visible_modules(student, Module.id).where(Module.id == module_id)) is None:
        raise ApiError(404, "not_found", "Module not found.")


def _ordered_modules(db: Session, student: Student, subject_id: uuid.UUID) -> list[Module]:
    return list(
        db.scalars(
            visible_modules(student)
            .where(Module.subject_id == subject_id)
            .order_by(Module.sort_order, Module.title)
        )
    )


@router.get("/subjects/{subject_id}/modules", response_model=list[ModuleOut])
def list_modules(
    subject_id: uuid.UUID,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
):
    _visible_subject_or_404(db, student, subject_id)
    modules = _ordered_modules(db, student, subject_id)
    counts = _counts_by(
        db,
        visible_contents(student, *_type_counts(Content.module_id))
        .where(Module.subject_id == subject_id)
        .group_by(Content.module_id),
    )
    completed = _completed_by(db, student, Content.module_id, Module.subject_id == subject_id)
    out = []
    for m in modules:
        total, videos, notes, images = counts.get(m.id, (0, 0, 0, 0))
        out.append(
            ModuleOut(
                id=m.id,
                subject_id=m.subject_id,
                title=m.title,
                description=m.description,
                sort_order=m.sort_order,
                content_count=total,
                video_count=videos,
                notes_count=notes,
                image_count=images,
                completed_count=completed.get(m.id, 0),
            )
        )
    return out


@router.get("/modules/{module_id}/contents", response_model=list[ContentOut])
def list_contents(
    module_id: uuid.UUID,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
):
    _visible_module_or_404(db, student, module_id)
    contents = db.scalars(
        visible_contents(student)
        .where(Content.module_id == module_id)
        .order_by(Content.sort_order, Content.title)
    ).all()
    progress = progress_by_content(db, student, [c.id for c in contents])
    return [content_out(c, progress.get(c.id)) for c in contents]


@router.get("/contents/{content_id}", response_model=ContentDetailOut)
def get_content(
    content_id: uuid.UUID,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
):
    row = db.execute(
        visible_contents(student, Content, Module.title, Subject.id, Subject.name).where(
            Content.id == content_id
        )
    ).first()
    if row is None:
        raise ApiError(404, "not_found", "This item is not available.")
    content, module_title, subject_id, subject_name = row
    base = content_out(content, progress_by_content(db, student, [content.id]).get(content.id))
    return ContentDetailOut(
        **base.model_dump(),
        module_title=module_title,
        subject_id=subject_id,
        subject_name=subject_name,
    )


@router.get("/me/continue", response_model=list[ContinueItemOut])
def continue_items(
    limit: int = Query(default=10, ge=1, le=100),
    include_completed: bool = False,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
):
    """Recently watched or opened items that are still available, newest first."""
    stmt = visible_contents(student, ContentProgress, Content, Module.title, Subject.name).join(
        ContentProgress,
        (ContentProgress.content_id == Content.id) & (ContentProgress.student_id == student.id),
    )
    if not include_completed:
        stmt = stmt.where(ContentProgress.is_completed.is_(False))
    rows = db.execute(stmt.order_by(ContentProgress.last_watched_at.desc()).limit(limit)).all()
    return [
        ContinueItemOut(content=content_out(content, progress), module_title=module, subject_name=subject)
        for progress, content, module, subject in rows
    ]


# --------------------------------------------------------------- legacy (app <= 1.0.x)


def progress_out(progress: ContentProgress | None) -> ProgressOut | None:
    if progress is None:
        return None
    return ProgressOut(
        video_id=progress.content_id,
        position_seconds=progress.position_seconds,
        duration_seconds=progress.duration_seconds,
        is_completed=progress.is_completed,
        last_watched_at=progress.last_watched_at,
    )


def video_out(content: Content, progress: ContentProgress | None) -> VideoOut:
    return VideoOut(
        id=content.id,
        chapter_id=content.module_id,
        title=content.title,
        description=content.description,
        duration_seconds=content.duration_seconds,
        sort_order=content.sort_order,
        progress=progress_out(progress),
    )


@router.get("/subjects/{subject_id}/chapters", response_model=list[ChapterOut], deprecated=True)
def list_chapters(
    subject_id: uuid.UUID,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
):
    _visible_subject_or_404(db, student, subject_id)
    modules = _ordered_modules(db, student, subject_id)
    video_counts = dict(
        db.execute(
            visible_contents(student, Content.module_id, func.count(Content.id), content_type=_VIDEO)
            .where(Module.subject_id == subject_id)
            .group_by(Content.module_id)
        ).all()
    )
    return [
        ChapterOut(
            id=m.id,
            subject_id=m.subject_id,
            title=m.title,
            description=m.description,
            sort_order=m.sort_order,
            video_count=video_counts.get(m.id, 0),
        )
        for m in modules
    ]


@router.get("/chapters/{chapter_id}/videos", response_model=list[VideoOut], deprecated=True)
def list_videos(
    chapter_id: uuid.UUID,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
):
    if db.scalar(visible_modules(student, Module.id).where(Module.id == chapter_id)) is None:
        raise ApiError(404, "not_found", "Chapter not found.")
    videos = db.scalars(
        visible_contents(student, content_type=_VIDEO)
        .where(Content.module_id == chapter_id)
        .order_by(Content.sort_order, Content.title)
    ).all()
    progress = progress_by_content(db, student, [v.id for v in videos])
    return [video_out(v, progress.get(v.id)) for v in videos]


@router.get("/videos/{video_id}", response_model=VideoDetailOut, deprecated=True)
def get_video(
    video_id: uuid.UUID,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
):
    row = db.execute(
        visible_contents(student, Content, Module.title, Subject.id, Subject.name, content_type=_VIDEO).where(
            Content.id == video_id
        )
    ).first()
    if row is None:
        raise ApiError(404, "not_found", "Lesson not found.")
    video, chapter_title, subject_id, subject_name = row
    base = video_out(video, progress_by_content(db, student, [video.id]).get(video.id))
    return VideoDetailOut(
        **base.model_dump(),
        chapter_title=chapter_title,
        subject_id=subject_id,
        subject_name=subject_name,
    )


@router.get("/me/recent", response_model=list[RecentVideoOut], deprecated=True)
def recent_videos(
    limit: int = Query(default=10, ge=1, le=50),
    include_completed: bool = True,
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
):
    """Recently watched videos that are still available, newest first."""
    stmt = visible_contents(
        student, ContentProgress, Content, Module.title, Subject.name, content_type=_VIDEO
    ).join(
        ContentProgress,
        (ContentProgress.content_id == Content.id) & (ContentProgress.student_id == student.id),
    )
    if not include_completed:
        stmt = stmt.where(ContentProgress.is_completed.is_(False))
    rows = db.execute(stmt.order_by(ContentProgress.last_watched_at.desc()).limit(limit)).all()
    return [
        RecentVideoOut(video=video_out(video, progress), chapter_title=chapter, subject_name=subject)
        for progress, video, chapter, subject in rows
    ]
