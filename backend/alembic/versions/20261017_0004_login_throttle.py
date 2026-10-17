"""per-account sign-in lock

``login_throttle`` counts recent wrong passwords per account (or per unknown name), so
that many tablets sharing one address (a router that translates addresses) can have a
high per-address sign-in limit while guessing one account's password stays slow.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-17
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "login_throttle",
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_login_throttle")),
    )


def downgrade() -> None:
    op.drop_table("login_throttle")
