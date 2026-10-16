"""What a student may see: one place for the catalogue visibility rules.

A student sees content of their own active class, in active subjects and
published chapters, and only published videos. Every catalogue, playback and
progress endpoint builds its query from these helpers.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, false, select

from .models import Chapter, SchoolClass, Student, Subject, Video, VideoStatus


def _subject_conditions(student: Student) -> list[Any]:
    if student.class_id is None:
        return [false()]
    return [
        Subject.class_id == student.class_id,
        Subject.is_active.is_(True),
        SchoolClass.is_active.is_(True),
    ]


def visible_subjects(student: Student, *columns: Any) -> Select:
    stmt = select(*columns) if columns else select(Subject)
    return (
        stmt.select_from(Subject)
        .join(SchoolClass, Subject.class_id == SchoolClass.id)
        .where(*_subject_conditions(student))
    )


def visible_chapters(student: Student, *columns: Any) -> Select:
    stmt = select(*columns) if columns else select(Chapter)
    return (
        stmt.select_from(Chapter)
        .join(Subject, Chapter.subject_id == Subject.id)
        .join(SchoolClass, Subject.class_id == SchoolClass.id)
        .where(*_subject_conditions(student), Chapter.is_published.is_(True))
    )


def visible_videos(student: Student, *columns: Any) -> Select:
    stmt = select(*columns) if columns else select(Video)
    return (
        stmt.select_from(Video)
        .join(Chapter, Video.chapter_id == Chapter.id)
        .join(Subject, Chapter.subject_id == Subject.id)
        .join(SchoolClass, Subject.class_id == SchoolClass.id)
        .where(
            *_subject_conditions(student),
            Chapter.is_published.is_(True),
            Video.status == VideoStatus.PUBLISHED.value,
        )
    )
