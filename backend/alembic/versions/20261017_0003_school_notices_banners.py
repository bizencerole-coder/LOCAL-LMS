"""school profile, notices and home-page banners

* ``school_profile``: the school's name, short name, tagline, colour and logo (one row),
  shown in the student app and set on the dashboard's School page;
* ``notices``: announcements for every student, one batch or one class;
* ``banners``: slides for the banner on the app's home page, optionally linking to a
  notice, subject or module.

Images (logo, banners) are files under VIDEO_ROOT/.branding, served by Nginx.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _timestamp(name: str, nullable: bool = False, default: bool = True) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.func.now() if default else None,
        nullable=nullable,
    )


def _audience(table: str) -> list:
    return [
        sa.Column("batch_id", sa.Uuid(), nullable=True),
        sa.Column("class_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["batches.id"], name=op.f(f"fk_{table}_batch_id_batches"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["class_id"], ["classes.id"], name=op.f(f"fk_{table}_class_id_classes"), ondelete="CASCADE"
        ),
        sa.CheckConstraint("batch_id IS NULL OR class_id IS NULL", name=op.f(f"ck_{table}_one_audience")),
    ]


def upgrade() -> None:
    op.create_table(
        "school_profile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("short_name", sa.String(length=40), nullable=True),
        sa.Column("tagline", sa.String(length=200), nullable=True),
        sa.Column("primary_color", sa.String(length=7), server_default="#2E5AAC", nullable=False),
        sa.Column("logo_file", sa.String(length=100), nullable=True),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_school_profile")),
    )

    op.create_table(
        "notices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        *_audience("notices"),
        sa.Column("is_important", sa.Boolean(), server_default=sa.false(), nullable=False),
        _timestamp("published_at", nullable=True, default=False),
        _timestamp("expires_at", nullable=True, default=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["created_by"], ["staff_users.id"], name=op.f("fk_notices_created_by_staff_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notices")),
    )
    op.create_index(op.f("ix_notices_batch_id"), "notices", ["batch_id"])
    op.create_index(op.f("ix_notices_class_id"), "notices", ["class_id"])
    op.create_index(op.f("ix_notices_published_at"), "notices", ["published_at"])

    op.create_table(
        "banners",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("subtitle", sa.String(length=240), nullable=True),
        sa.Column("image_file", sa.String(length=100), nullable=True),
        sa.Column("link_type", sa.String(length=20), nullable=True),
        sa.Column("link_id", sa.Uuid(), nullable=True),
        *_audience("banners"),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        _timestamp("starts_at", nullable=True, default=False),
        _timestamp("ends_at", nullable=True, default=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "link_type IS NULL OR link_type IN ('notice', 'subject', 'module')",
            name=op.f("ck_banners_link_type_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_banners")),
    )
    op.create_index(op.f("ix_banners_batch_id"), "banners", ["batch_id"])
    op.create_index(op.f("ix_banners_class_id"), "banners", ["class_id"])


def downgrade() -> None:
    op.drop_table("banners")
    op.drop_table("notices")
    op.drop_table("school_profile")
