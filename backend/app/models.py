"""SQLAlchemy models.

Content hierarchy: Batch -> Class -> Subject -> Module -> Content (video, PDF notes, image).
Every level also has a ``folder`` name: the matching directory under VIDEO_ROOT, so the
files on the server mirror what the app shows (``<batch>/<class>/<subject>/<module>/<file>``).
Display names can change freely; folders are fixed when an item is created.

Schema changes must go through Alembic migrations in ``alembic/versions``.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    false,
    func,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ContentStatus(enum.StrEnum):
    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ContentType(enum.StrEnum):
    VIDEO = "video"
    PDF = "pdf"  # shown to students as "Notes"
    IMAGE = "image"


class StaffRole(enum.StrEnum):
    ADMIN = "admin"  # everything, including staff accounts
    STAFF = "staff"  # content and students


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())


def _updated() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )


class Batch(Base):
    """A cohort or academic year, e.g. "Batch 2026-27". Holds classes."""

    __tablename__ = "batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    folder: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    classes: Mapped[list[SchoolClass]] = relationship(back_populates="batch")


class SchoolClass(Base):
    """A class/grade such as "Class 12" within a batch. Named to avoid the Python keyword."""

    __tablename__ = "classes"
    __table_args__ = (
        UniqueConstraint("batch_id", "name", name="uq_classes_batch_id_name"),
        UniqueConstraint("batch_id", "folder", name="uq_classes_batch_id_folder"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("batches.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    folder: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = _created()

    batch: Mapped[Batch] = relationship(back_populates="classes")
    subjects: Mapped[list[Subject]] = relationship(back_populates="school_class")
    students: Mapped[list[Student]] = relationship(back_populates="school_class")


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Stored upper-case; login matches case-insensitively.
    student_code: Mapped[str] = mapped_column(String(50), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    # Stored lower-case; login matches case-insensitively.
    username: Mapped[str] = mapped_column(String(100), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classes.id", ondelete="RESTRICT"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    school_class: Mapped[SchoolClass | None] = relationship(back_populates="students")


class Subject(Base):
    __tablename__ = "subjects"
    __table_args__ = (
        UniqueConstraint("class_id", "name", name="uq_subjects_class_id_name"),
        UniqueConstraint("class_id", "folder", name="uq_subjects_class_id_folder"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    class_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("classes.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    folder: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = _created()

    school_class: Mapped[SchoolClass] = relationship(back_populates="subjects")
    modules: Mapped[list[Module]] = relationship(back_populates="subject")


class Module(Base):
    """A unit of a subject (formerly "chapter"). ``folder`` is empty for files that sit
    directly in the subject folder (shown as a module called "General")."""

    __tablename__ = "modules"
    __table_args__ = (
        UniqueConstraint("subject_id", "title", name="uq_modules_subject_id_title"),
        UniqueConstraint("subject_id", "folder", name="uq_modules_subject_id_folder"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subject_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("subjects.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    folder: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = _created()

    subject: Mapped[Subject] = relationship(back_populates="modules")
    contents: Mapped[list[Content]] = relationship(back_populates="module")


class Content(Base):
    """One item a student opens: a video, PDF notes or an image."""

    __tablename__ = "contents"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="status_valid"),
        CheckConstraint("content_type IN ('video', 'pdf', 'image')", name="content_type_valid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    module_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("modules.id", ondelete="RESTRICT"), index=True
    )
    content_type: Mapped[str] = mapped_column(
        String(20), default=ContentType.VIDEO.value, server_default=ContentType.VIDEO.value
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # Relative to VIDEO_ROOT, server-managed, never supplied by the student app.
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    mime_type: Mapped[str] = mapped_column(
        String(100), default="video/mp4", server_default="video/mp4"
    )
    resolution_width: Mapped[int | None] = mapped_column(Integer)
    resolution_height: Mapped[int | None] = mapped_column(Integer)
    # SHA-256 of the file (uploads, notes and images), used to follow moved files.
    checksum: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(20),
        default=ContentStatus.DRAFT.value,
        server_default=ContentStatus.DRAFT.value,
        index=True,
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    module: Mapped[Module] = relationship(back_populates="contents")

    @property
    def is_video(self) -> bool:
        return self.content_type == ContentType.VIDEO.value


class ContentProgress(Base):
    """Per-student progress: playback position for videos, "opened" for notes and images."""

    __tablename__ = "student_content_progress"
    __table_args__ = (
        UniqueConstraint(
            "student_id", "content_id", name="uq_student_content_progress_student_content"
        ),
        Index("ix_student_content_progress_student_last_watched", "student_id", "last_watched_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    content_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("contents.id", ondelete="CASCADE"), index=True
    )
    position_seconds: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_watched_at: Mapped[datetime] = _created()


class AuthSession(Base):
    """Student bearer-token session. Only a SHA-256 hash of the token is stored."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    student_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    student: Mapped[Student] = relationship()


class LoginThrottle(Base):
    """Recent wrong passwords per account ("student:<id>") or per unknown name
    ("name:<what was typed>"), for the sign-in lock (LOGIN_MAX_FAILURES)."""

    __tablename__ = "login_throttle"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    first_failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StaffUser(Base):
    """A teacher or administrator who signs in to the web dashboard."""

    __tablename__ = "staff_users"
    __table_args__ = (CheckConstraint("role IN ('admin', 'staff')", name="role_valid"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Stored lower-case.
    username: Mapped[str] = mapped_column(String(100), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(
        String(20), default=StaffRole.STAFF.value, server_default=StaffRole.STAFF.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_admin(self) -> bool:
        return self.role == StaffRole.ADMIN.value


class StaffSession(Base):
    """Dashboard session (HttpOnly cookie). Only a SHA-256 hash of the token is stored."""

    __tablename__ = "staff_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    staff_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("staff_users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    staff: Mapped[StaffUser] = relationship()


DEFAULT_SCHOOL_NAME = "Campus LMS"
DEFAULT_SCHOOL_COLOR = "#2E5AAC"


class SchoolProfile(Base):
    """The school's name, logo and colour, shown in the student app and on the dashboard.

    One row (id 1), created when an administrator first saves the School page; until
    then the defaults above are used.
    """

    __tablename__ = "school_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    short_name: Mapped[str | None] = mapped_column(String(40))
    tagline: Mapped[str | None] = mapped_column(String(200))
    # "#RRGGBB"; the app builds its colour scheme from it.
    primary_color: Mapped[str] = mapped_column(
        String(7), default=DEFAULT_SCHOOL_COLOR, server_default=DEFAULT_SCHOOL_COLOR
    )
    # File name under VIDEO_ROOT/.branding, served by Nginx at /branding/<name>.
    logo_file: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = _updated()


class Notice(Base):
    """An announcement in the app's Notices: for every student, one batch or one class."""

    __tablename__ = "notices"
    __table_args__ = (CheckConstraint("batch_id IS NULL OR class_id IS NULL", name="one_audience"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str | None] = mapped_column(Text)
    # Neither set: every student. batch_id: the batch's classes. class_id: that class.
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"), index=True
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True
    )
    is_important: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # When it was published (again); null while it is a draft.
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class BannerLink(enum.StrEnum):
    NOTICE = "notice"
    SUBJECT = "subject"
    MODULE = "module"


class Banner(Base):
    """A slide in the banner at the top of the app's home page."""

    __tablename__ = "banners"
    __table_args__ = (
        CheckConstraint("batch_id IS NULL OR class_id IS NULL", name="one_audience"),
        CheckConstraint(
            "link_type IS NULL OR link_type IN ('notice', 'subject', 'module')", name="link_type_valid"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(120))
    subtitle: Mapped[str | None] = mapped_column(String(240))
    # File name under VIDEO_ROOT/.branding; without one the app shows the school colour.
    image_file: Mapped[str | None] = mapped_column(String(100))
    # What a tap opens. Shown only when the student may see it (else the slide just shows).
    link_type: Mapped[str | None] = mapped_column(String(20))
    link_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("batches.id", ondelete="CASCADE"), index=True
    )
    class_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("classes.id", ondelete="CASCADE"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class SyncRun(Base):
    """One run of the folder sync (cron/CLI or the dashboard), shown on the dashboard."""

    __tablename__ = "sync_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    trigger: Mapped[str] = mapped_column(String(20))  # "cli" or "dashboard"
    staff_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("staff_users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = _created()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    registered: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    moved: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    archived: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    skipped: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    problems: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    report: Mapped[str | None] = mapped_column(Text)
