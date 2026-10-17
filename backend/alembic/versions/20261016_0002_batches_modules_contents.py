"""batches, modules and typed contents; staff accounts; sync runs

Turns the class -> subject -> chapter -> video catalogue into
batch -> class -> subject -> module -> content (video, PDF notes, image):

* creates the table ``batches`` and, when classes exist, one batch for the current
  academic year (e.g. "Batch 2026-27", folder ``batch-2026-27``) that gets every class;
* gives classes, subjects and modules a ``folder`` (their directory under VIDEO_ROOT),
  taken from the existing storage keys, so uploads land next to the existing files;
* renames chapters -> modules, videos -> contents (+ content_type, checksum),
  student_video_progress -> student_content_progress (rows and progress are kept);
* prefixes every storage key with the batch folder. The files themselves are moved by
  ``python -m app.cli relocate-content --apply`` (run automatically at API start);
* adds staff_users, staff_sessions (web dashboard) and sync_runs.

Downgrade is not supported: restore the backup taken before the upgrade.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-16
"""
import re
import unicodedata
import uuid
from collections import Counter
from datetime import date
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamp(name: str, nullable: bool = False, default: bool = True) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.func.now() if default else None,
        nullable=nullable,
    )


def academic_year(today: date) -> str:
    """'2026-27' for dates from June 2026 to May 2027."""
    start = today.year if today.month >= 6 else today.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")[:60].rstrip("-")
    return value or "item"


def _unique(wanted: str, taken: set[str]) -> str:
    name, n = wanted, 2
    while name in taken:
        name = f"{wanted}-{n}"
        n += 1
    taken.add(name)
    return name


def plan_folders(
    classes: list[tuple],  # (id, name)
    subjects: list[tuple],  # (id, class_id, name)
    modules: list[tuple],  # (id, subject_id, title)
    keys: list[tuple],  # (storage_key, module_id)
) -> tuple[dict, dict, dict]:
    """Folder names for existing classes, subjects and modules, from their files' keys.

    Legacy keys look like <class>/<subject>/<chapter>/<file> or <class>/<subject>/<file>.
    """
    subject_of_module = {m_id: s_id for m_id, s_id, _ in modules}
    class_of_subject = {s_id: c_id for s_id, c_id, _ in subjects}
    class_votes: dict = {}
    subject_votes: dict = {}
    module_votes: dict = {}
    for key, module_id in keys:
        parts = key.split("/")
        subject_id = subject_of_module.get(module_id)
        class_id = class_of_subject.get(subject_id)
        if len(parts) >= 2:
            class_votes.setdefault(class_id, Counter())[parts[0]] += 1
        if len(parts) >= 3:
            subject_votes.setdefault(subject_id, Counter())[parts[1]] += 1
        module_votes.setdefault(module_id, Counter())[parts[2] if len(parts) >= 4 else ""] += 1

    class_folders: dict = {}
    taken: set[str] = set()
    for class_id, name in classes:
        votes = class_votes.get(class_id)
        class_folders[class_id] = _unique(votes.most_common(1)[0][0] if votes else slug(name), taken)

    subject_folders: dict = {}
    taken_by_class: dict = {}
    for subject_id, class_id, name in subjects:
        votes = subject_votes.get(subject_id)
        wanted = votes.most_common(1)[0][0] if votes else slug(name)
        subject_folders[subject_id] = _unique(wanted, taken_by_class.setdefault(class_id, set()))

    module_folders: dict = {}
    taken_by_subject: dict = {}
    for module_id, subject_id, title in modules:
        votes = module_votes.get(module_id)
        wanted = votes.most_common(1)[0][0] if votes else slug(title)
        taken = taken_by_subject.setdefault(subject_id, set())
        if wanted == "" and "" in taken:
            wanted = slug(title)
        module_folders[module_id] = "" if wanted == "" else _unique(wanted, taken)
        if wanted == "":
            taken.add("")
    return class_folders, subject_folders, module_folders


_PG_RENAMES = [
    # (table, old constraint, new constraint)
    ("modules", "pk_chapters", "pk_modules"),
    ("modules", "fk_chapters_subject_id_subjects", "fk_modules_subject_id_subjects"),
    ("modules", "uq_chapters_subject_id_title", "uq_modules_subject_id_title"),
    ("contents", "pk_videos", "pk_contents"),
    ("contents", "fk_videos_chapter_id_chapters", "fk_contents_module_id_modules"),
    ("contents", "uq_videos_storage_key", "uq_contents_storage_key"),
    ("contents", "ck_videos_status_valid", "ck_contents_status_valid"),
    ("student_content_progress", "pk_student_video_progress", "pk_student_content_progress"),
    (
        "student_content_progress",
        "fk_student_video_progress_student_id_students",
        "fk_student_content_progress_student_id_students",
    ),
    (
        "student_content_progress",
        "fk_student_video_progress_video_id_videos",
        "fk_student_content_progress_content_id_contents",
    ),
    (
        "student_content_progress",
        "uq_student_video_progress_student_video",
        "uq_student_content_progress_student_content",
    ),
]
_PG_INDEX_RENAMES = [
    ("ix_chapters_subject_id", "ix_modules_subject_id"),
    ("ix_videos_chapter_id", "ix_contents_module_id"),
    ("ix_videos_status", "ix_contents_status"),
    ("ix_student_video_progress_student_last_watched", "ix_student_content_progress_student_last_watched"),
    ("ix_student_video_progress_video_id", "ix_student_content_progress_content_id"),
]


def upgrade() -> None:
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"

    op.create_table(
        "batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("folder", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_batches")),
        sa.UniqueConstraint("name", name=op.f("uq_batches_name")),
        sa.UniqueConstraint("folder", name=op.f("uq_batches_folder")),
    )

    op.add_column("classes", sa.Column("batch_id", sa.Uuid(), nullable=True))
    op.add_column("classes", sa.Column("folder", sa.String(length=100), nullable=True))
    op.add_column("classes", sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False))
    op.add_column("subjects", sa.Column("folder", sa.String(length=100), nullable=True))
    op.add_column("subjects", sa.Column("description", sa.Text(), nullable=True))

    op.rename_table("chapters", "modules")
    op.add_column("modules", sa.Column("folder", sa.String(length=100), nullable=True))

    op.rename_table("videos", "contents")
    op.alter_column("contents", "chapter_id", new_column_name="module_id")
    op.add_column(
        "contents", sa.Column("content_type", sa.String(length=20), server_default="video", nullable=False)
    )
    op.add_column("contents", sa.Column("checksum", sa.String(length=64), nullable=True))

    op.rename_table("student_video_progress", "student_content_progress")
    op.alter_column("student_content_progress", "video_id", new_column_name="content_id")

    # --- data: one batch for the existing classes, folders from the storage keys
    batches = sa.table(
        "batches",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("folder", sa.String()),
        sa.column("description", sa.Text()),
    )
    classes = sa.table(
        "classes", sa.column("id", sa.Uuid()), sa.column("name", sa.String()),
        sa.column("batch_id", sa.Uuid()), sa.column("folder", sa.String()),
    )
    subjects = sa.table(
        "subjects", sa.column("id", sa.Uuid()), sa.column("class_id", sa.Uuid()),
        sa.column("name", sa.String()), sa.column("folder", sa.String()),
    )
    modules = sa.table(
        "modules", sa.column("id", sa.Uuid()), sa.column("subject_id", sa.Uuid()),
        sa.column("title", sa.String()), sa.column("folder", sa.String()),
    )
    contents = sa.table(
        "contents", sa.column("id", sa.Uuid()), sa.column("module_id", sa.Uuid()),
        sa.column("storage_key", sa.String()),
    )

    class_rows = bind.execute(sa.select(classes.c.id, classes.c.name).order_by(classes.c.name)).all()
    if class_rows:
        year = academic_year(date.today())
        batch_id, batch_folder = uuid.uuid4(), f"batch-{year}"
        bind.execute(
            batches.insert().values(
                id=batch_id,
                name=f"Batch {year}",
                folder=batch_folder,
                description="Created by the upgrade that introduced batches.",
            )
        )
        subject_rows = bind.execute(sa.select(subjects.c.id, subjects.c.class_id, subjects.c.name)).all()
        module_rows = bind.execute(sa.select(modules.c.id, modules.c.subject_id, modules.c.title)).all()
        key_rows = bind.execute(sa.select(contents.c.storage_key, contents.c.module_id)).all()
        class_folders, subject_folders, module_folders = plan_folders(
            [tuple(r) for r in class_rows],
            [tuple(r) for r in subject_rows],
            [tuple(r) for r in module_rows],
            [tuple(r) for r in key_rows],
        )
        for class_id, folder in class_folders.items():
            bind.execute(
                classes.update().where(classes.c.id == class_id).values(batch_id=batch_id, folder=folder)
            )
        for subject_id, folder in subject_folders.items():
            bind.execute(subjects.update().where(subjects.c.id == subject_id).values(folder=folder))
        for module_id, folder in module_folders.items():
            bind.execute(modules.update().where(modules.c.id == module_id).values(folder=folder))
        bind.execute(contents.update().values(storage_key=sa.literal(batch_folder + "/") + contents.c.storage_key))

    op.alter_column("classes", "batch_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("classes", "folder", existing_type=sa.String(length=100), nullable=False)
    op.alter_column("subjects", "folder", existing_type=sa.String(length=100), nullable=False)
    op.alter_column("modules", "folder", existing_type=sa.String(length=100), nullable=False)

    op.create_foreign_key(
        op.f("fk_classes_batch_id_batches"), "classes", "batches", ["batch_id"], ["id"], ondelete="RESTRICT"
    )
    op.create_index(op.f("ix_classes_batch_id"), "classes", ["batch_id"])
    op.drop_constraint("uq_classes_name", "classes", type_="unique")
    op.create_unique_constraint("uq_classes_batch_id_name", "classes", ["batch_id", "name"])
    op.create_unique_constraint("uq_classes_batch_id_folder", "classes", ["batch_id", "folder"])
    op.create_unique_constraint("uq_subjects_class_id_folder", "subjects", ["class_id", "folder"])
    op.create_unique_constraint("uq_modules_subject_id_folder", "modules", ["subject_id", "folder"])
    op.create_check_constraint(
        op.f("ck_contents_content_type_valid"), "contents", "content_type IN ('video', 'pdf', 'image')"
    )

    if postgres:
        for table, old, new in _PG_RENAMES:
            op.execute(f'ALTER TABLE "{table}" RENAME CONSTRAINT "{old}" TO "{new}"')
        for old, new in _PG_INDEX_RENAMES:
            op.execute(f'ALTER INDEX "{old}" RENAME TO "{new}"')

    op.create_table(
        "staff_users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), server_default="staff", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        _timestamp("last_login_at", nullable=True, default=False),
        sa.CheckConstraint("role IN ('admin', 'staff')", name=op.f("ck_staff_users_role_valid")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_users")),
        sa.UniqueConstraint("username", name=op.f("uq_staff_users_username")),
    )
    op.create_table(
        "staff_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("staff_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        _timestamp("created_at"),
        _timestamp("expires_at", default=False),
        _timestamp("revoked_at", nullable=True, default=False),
        sa.ForeignKeyConstraint(
            ["staff_id"], ["staff_users.id"],
            name=op.f("fk_staff_sessions_staff_id_staff_users"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_staff_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_staff_sessions_token_hash")),
    )
    op.create_index(op.f("ix_staff_sessions_staff_id"), "staff_sessions", ["staff_id"])
    op.create_index(op.f("ix_staff_sessions_expires_at"), "staff_sessions", ["expires_at"])
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("staff_id", sa.Uuid(), nullable=True),
        _timestamp("started_at"),
        _timestamp("finished_at", nullable=True, default=False),
        *[
            sa.Column(name, sa.Integer(), server_default="0", nullable=False)
            for name in ("registered", "moved", "updated", "archived", "skipped", "problems")
        ],
        sa.Column("report", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["staff_id"], ["staff_users.id"],
            name=op.f("fk_sync_runs_staff_id_staff_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_runs")),
    )
    op.create_index(op.f("ix_sync_runs_finished_at"), "sync_runs", ["finished_at"])


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrading past 0002 is not supported. Restore the database backup taken before the "
        "upgrade (deploy/scripts/restore.sh) and move the content folders back out of the batch folder."
    )
