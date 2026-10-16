"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamp(name: str, nullable: bool = False, default: bool = True) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.func.now() if default else None,
        nullable=nullable,
    )


def upgrade() -> None:
    op.create_table(
        "classes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        _timestamp("created_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classes")),
        sa.UniqueConstraint("name", name=op.f("uq_classes_name")),
    )

    op.create_table(
        "students",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_code", sa.String(length=50), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("class_id", sa.Uuid(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["class_id"], ["classes.id"],
            name=op.f("fk_students_class_id_classes"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_students")),
        sa.UniqueConstraint("student_code", name=op.f("uq_students_student_code")),
        sa.UniqueConstraint("username", name=op.f("uq_students_username")),
    )
    op.create_index(op.f("ix_students_class_id"), "students", ["class_id"])

    op.create_table(
        "subjects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("class_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        _timestamp("created_at"),
        sa.ForeignKeyConstraint(
            ["class_id"], ["classes.id"],
            name=op.f("fk_subjects_class_id_classes"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subjects")),
        sa.UniqueConstraint("class_id", "name", name="uq_subjects_class_id_name"),
    )
    op.create_index(op.f("ix_subjects_class_id"), "subjects", ["class_id"])

    op.create_table(
        "chapters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_published", sa.Boolean(), server_default=sa.false(), nullable=False),
        _timestamp("created_at"),
        sa.ForeignKeyConstraint(
            ["subject_id"], ["subjects.id"],
            name=op.f("fk_chapters_subject_id_subjects"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chapters")),
        sa.UniqueConstraint("subject_id", "title", name="uq_chapters_subject_id_title"),
    )
    op.create_index(op.f("ix_chapters_subject_id"), "chapters", ["subject_id"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        _timestamp("created_at"),
        _timestamp("expires_at", default=False),
        _timestamp("revoked_at", nullable=True, default=False),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"],
            name=op.f("fk_sessions_student_id_students"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"])
    op.create_index(op.f("ix_sessions_student_id"), "sessions", ["student_id"])

    op.create_table(
        "videos",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("chapter_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("mime_type", sa.String(length=100), server_default="video/mp4", nullable=False),
        sa.Column("resolution_width", sa.Integer(), nullable=True),
        sa.Column("resolution_height", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')", name=op.f("ck_videos_status_valid")
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"], ["chapters.id"],
            name=op.f("fk_videos_chapter_id_chapters"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_videos")),
        sa.UniqueConstraint("storage_key", name=op.f("uq_videos_storage_key")),
    )
    op.create_index(op.f("ix_videos_chapter_id"), "videos", ["chapter_id"])
    op.create_index(op.f("ix_videos_status"), "videos", ["status"])

    op.create_table(
        "student_video_progress",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("student_id", sa.Uuid(), nullable=False),
        sa.Column("video_id", sa.Uuid(), nullable=False),
        sa.Column("position_seconds", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("is_completed", sa.Boolean(), server_default=sa.false(), nullable=False),
        _timestamp("completed_at", nullable=True, default=False),
        _timestamp("last_watched_at"),
        sa.ForeignKeyConstraint(
            ["student_id"], ["students.id"],
            name=op.f("fk_student_video_progress_student_id_students"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["video_id"], ["videos.id"],
            name=op.f("fk_student_video_progress_video_id_videos"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student_video_progress")),
        sa.UniqueConstraint(
            "student_id", "video_id", name="uq_student_video_progress_student_video"
        ),
    )
    op.create_index(
        "ix_student_video_progress_student_last_watched",
        "student_video_progress",
        ["student_id", "last_watched_at"],
    )
    op.create_index(
        op.f("ix_student_video_progress_video_id"), "student_video_progress", ["video_id"]
    )


def downgrade() -> None:
    op.drop_table("student_video_progress")
    op.drop_table("videos")
    op.drop_table("sessions")
    op.drop_table("chapters")
    op.drop_table("subjects")
    op.drop_table("students")
    op.drop_table("classes")
