"""What a student may see: one place for the catalogue visibility rules.

A student sees content of their own class while the class and its batch are active,
in active subjects and published modules, and only published content. Every
catalogue, playback and progress endpoint builds its query from these helpers.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, false, select

from .models import (
    Batch,
    Content,
    ContentStatus,
    Module,
    SchoolClass,
    Student,
    Subject,
)


def _subject_conditions(student: Student) -> list[Any]:
    if student.class_id is None:
        return [false()]
    return [
        Subject.class_id == student.class_id,
        Subject.is_active.is_(True),
        SchoolClass.is_active.is_(True),
        Batch.is_active.is_(True),
    ]


def _join_up(stmt: Select) -> Select:
    return stmt.join(SchoolClass, Subject.class_id == SchoolClass.id).join(
        Batch, SchoolClass.batch_id == Batch.id
    )


def visible_subjects(student: Student, *columns: Any) -> Select:
    stmt = select(*columns) if columns else select(Subject)
    return _join_up(stmt.select_from(Subject)).where(*_subject_conditions(student))


def visible_modules(student: Student, *columns: Any) -> Select:
    stmt = select(*columns) if columns else select(Module)
    return _join_up(
        stmt.select_from(Module).join(Subject, Module.subject_id == Subject.id)
    ).where(*_subject_conditions(student), Module.is_published.is_(True))


def visible_contents(student: Student, *columns: Any, content_type: str | None = None) -> Select:
    stmt = select(*columns) if columns else select(Content)
    stmt = _join_up(
        stmt.select_from(Content)
        .join(Module, Content.module_id == Module.id)
        .join(Subject, Module.subject_id == Subject.id)
    ).where(
        *_subject_conditions(student),
        Module.is_published.is_(True),
        Content.status == ContentStatus.PUBLISHED.value,
    )
    if content_type is not None:
        stmt = stmt.where(Content.content_type == content_type)
    return stmt
