"""The school's look in the student app: name, colour, logo, notices and banners.

Images (the logo and banner pictures) are files in VIDEO_ROOT/.branding, a hidden folder
the folder sync ignores, named after their content (``logo-<hash>.png``). Nginx serves
them at ``/branding/<name>`` with long caching: a changed image gets a new name.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session

from .fileinfo import sniff_image
from .models import (
    DEFAULT_SCHOOL_COLOR,
    DEFAULT_SCHOOL_NAME,
    Banner,
    Batch,
    Notice,
    SchoolClass,
    SchoolProfile,
    Student,
)
from .storage import FILE_MODE, ensure_dir

BRANDING_DIR = ".branding"
URL_PREFIX = "/branding/"
MAX_LOGO_BYTES = 1024 * 1024
MAX_BANNER_BYTES = 3 * 1024 * 1024
_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
_NAME_RE = re.compile(r"^(logo|banner)-[0-9a-f]{20}\.(png|jpg|webp)$")
COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class BrandingImageError(ValueError):
    """Not an image the app can show (type or size)."""


def save_image(root: Path, data: bytes, kind: str, *, max_bytes: int) -> str:
    """Check ``data`` is a PNG, JPEG or WebP image and store it; returns its file name."""
    if not data:
        raise BrandingImageError("The image file is empty.")
    if len(data) > max_bytes:
        raise BrandingImageError(f"The image is larger than {max_bytes // (1024 * 1024)} MB.")
    sniffed = sniff_image(data)
    if sniffed is None:
        raise BrandingImageError("Only PNG, JPEG and WebP images can be used.")
    name = f"{kind}-{hashlib.sha256(data).hexdigest()[:20]}{_EXTENSIONS[sniffed[0]]}"
    folder = root / BRANDING_DIR
    ensure_dir(folder)
    final = folder / name
    if not final.exists():
        temp = folder / f".{uuid.uuid4().hex}.part"
        try:
            temp.write_bytes(data)
            with contextlib.suppress(OSError):
                os.chmod(temp, FILE_MODE)
            os.replace(temp, final)
        finally:
            temp.unlink(missing_ok=True)
    return name


def remove_image_if_unused(db: Session, root: Path, name: str | None) -> None:
    """Delete an image file no school profile or banner refers to any more."""
    if not name or not _NAME_RE.match(name):
        return
    used = db.scalar(select(func.count()).select_from(Banner).where(Banner.image_file == name))
    used += db.scalar(select(func.count()).select_from(SchoolProfile).where(SchoolProfile.logo_file == name))
    if not used:
        with contextlib.suppress(OSError):
            (root / BRANDING_DIR / name).unlink(missing_ok=True)


def image_url(name: str | None) -> str | None:
    return f"{URL_PREFIX}{name}" if name else None


def school_profile(db: Session) -> SchoolProfile:
    """The saved profile, or an unsaved one with the defaults."""
    return db.get(SchoolProfile, 1) or SchoolProfile(
        id=1, name=DEFAULT_SCHOOL_NAME, primary_color=DEFAULT_SCHOOL_COLOR
    )


# ------------------------------------------------------------------ audiences


def student_batch_id(db: Session, student: Student) -> uuid.UUID | None:
    if student.class_id is None:
        return None
    return db.scalar(select(SchoolClass.batch_id).where(SchoolClass.id == student.class_id))


def for_student(model, student: Student, batch_id: uuid.UUID | None) -> ColumnElement[bool]:
    """Rows of ``model`` (Notice or Banner) addressed to this student."""
    everyone = and_(model.batch_id.is_(None), model.class_id.is_(None))
    if student.class_id is None:
        return everyone
    return or_(everyone, model.class_id == student.class_id, model.batch_id == batch_id)


def visible_notices(student: Student, batch_id: uuid.UUID | None, now: datetime):
    return select(Notice).where(
        Notice.published_at.is_not(None),
        Notice.published_at <= now,
        or_(Notice.expires_at.is_(None), Notice.expires_at > now),
        for_student(Notice, student, batch_id),
    )


def audience_label(db: Session, batch_id: uuid.UUID | None, class_id: uuid.UUID | None) -> str:
    if class_id is not None:
        row = db.execute(
            select(SchoolClass.name, Batch.name)
            .join(Batch, SchoolClass.batch_id == Batch.id)
            .where(SchoolClass.id == class_id)
        ).first()
        return f"{row[1]} › {row[0]}" if row else "One class"
    if batch_id is not None:
        name = db.scalar(select(Batch.name).where(Batch.id == batch_id))
        return name or "One batch"
    return "All students"
