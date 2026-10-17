"""Folders and files under VIDEO_ROOT for the content hierarchy.

Layout: ``<batch>/<class>/<subject>/<module>/<NN-name>.<ext>`` (a module with an empty
folder name means files directly in the subject folder). Each folder created by the
dashboard gets a ``title.txt`` with its display name, and each uploaded file a
``<name>.txt`` sidecar (title, then description), so the folders describe themselves:
the folder sync rebuilds the same names on a new server.

Hidden folders under the root are never content: ``.uploads`` (dashboard uploads in
progress) and ``.trash`` (deleted files, kept for 30 days).
"""

from __future__ import annotations

import contextlib
import os
import shutil
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from .media import is_valid_folder, slugify
from .models import Batch, Content, Module, SchoolClass, Subject

UPLOADS_DIR = ".uploads"
TRASH_DIR = ".trash"
DIR_MODE = 0o2775  # group-writable, new files keep the folder's group (network share users)
FILE_MODE = 0o664
TITLE_FILE = "title.txt"
UPLOAD_MAX_AGE_SECONDS = 24 * 3600
TRASH_MAX_AGE_SECONDS = 30 * 24 * 3600

_LOCK_KEY = 0x4C4D5301  # pg_advisory_xact_lock key for catalogue file changes


def catalogue_lock(db: Session) -> None:
    """Serialise changes to catalogue files (sync, uploads, moves) across processes.

    Transaction-scoped: released at commit or rollback. No-op on SQLite (tests).
    """
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _LOCK_KEY})


# --------------------------------------------------------------------------- paths


def batch_rel(batch: Batch) -> str:
    return batch.folder


def class_rel(batch: Batch, school_class: SchoolClass) -> str:
    return f"{batch.folder}/{school_class.folder}"


def subject_rel(batch: Batch, school_class: SchoolClass, subject: Subject) -> str:
    return f"{class_rel(batch, school_class)}/{subject.folder}"


def module_rel(batch: Batch, school_class: SchoolClass, subject: Subject, module: Module) -> str:
    base = subject_rel(batch, school_class, subject)
    return f"{base}/{module.folder}" if module.folder else base


def module_chain(db: Session, module: Module) -> tuple[Batch, SchoolClass, Subject]:
    subject = db.get(Subject, module.subject_id)
    school_class = db.get(SchoolClass, subject.class_id)
    batch = db.get(Batch, school_class.batch_id)
    return batch, school_class, subject


def module_dir(db: Session, root: Path, module: Module) -> Path:
    batch, school_class, subject = module_chain(db, module)
    return root.joinpath(*module_rel(batch, school_class, subject, module).split("/"))


def path_for_key(root: Path, key: str) -> Path:
    return root.joinpath(*key.split("/"))


# --------------------------------------------------------------------------- folders


def ensure_dir(path: Path) -> None:
    """Create ``path`` (and parents) group-writable. Existing folders are left alone."""
    missing = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    for folder in reversed(missing):
        with contextlib.suppress(FileExistsError):
            folder.mkdir()
        _chmod(folder, DIR_MODE)


def _chmod(path: Path, mode: int) -> None:
    # Not possible on some mounts (e.g. Windows bind mounts); the files still work.
    with contextlib.suppress(OSError):
        os.chmod(path, mode)


def write_text_file(path: Path, body: str) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(body, encoding="utf-8")
    _chmod(tmp, FILE_MODE)
    os.replace(tmp, path)


def write_title_file(folder: Path, title: str) -> None:
    ensure_dir(folder)
    write_text_file(folder / TITLE_FILE, title.strip() + "\n")


def sidecar_path(file_path: Path) -> Path:
    return file_path.with_suffix(".txt")


def write_sidecar(file_path: Path, title: str, description: str | None) -> None:
    body = title.strip() + "\n"
    if description and description.strip():
        body += description.strip() + "\n"
    write_text_file(sidecar_path(file_path), body)


def unique_folder(parent: Path, wanted: str, taken: set[str]) -> str:
    """A folder name under ``parent`` not used on disk or in ``taken``."""
    base = wanted if is_valid_folder(wanted) else slugify(wanted)
    name, n = base, 2
    while name in taken or (parent / name).exists():
        name = f"{base}-{n}"
        n += 1
    return name


def unique_file_name(folder: Path, stem: str, ext: str) -> str:
    name, n = f"{stem}{ext}", 2
    while (folder / name).exists() or sidecar_path(folder / name).exists():
        name = f"{stem}-{n}{ext}"
        n += 1
    return name


def content_file_stem(order: int, title: str) -> str:
    return f"{order:02d}-{slugify(title, max_length=50, fallback='file')}"


def remove_folder_if_unused(folder: Path) -> bool:
    """Delete a folder that holds nothing but its title.txt. True if it is gone."""
    if not folder.exists():
        return True
    leftovers = [p for p in folder.iterdir() if p.name != TITLE_FILE]
    if leftovers:
        return False
    with contextlib.suppress(FileNotFoundError):
        (folder / TITLE_FILE).unlink()
    folder.rmdir()
    return True


# --------------------------------------------------------------------------- files


def move_file(src: Path, dst: Path) -> None:
    """Move within VIDEO_ROOT (same filesystem: an atomic rename)."""
    ensure_dir(dst.parent)
    if dst.exists():
        raise FileExistsError(dst)
    os.replace(src, dst)
    side = sidecar_path(src)
    if side.exists() and not sidecar_path(dst).exists():
        os.replace(side, sidecar_path(dst))


def move_to_trash(root: Path, key: str) -> Path | None:
    """Move a content file (and its sidecar) to .trash/<timestamp>/<key>. None if missing."""
    src = path_for_key(root, key)
    if not src.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    dst = root / TRASH_DIR / stamp / Path(*key.split("/"))
    ensure_dir(dst.parent)
    os.replace(src, dst)
    side = sidecar_path(src)
    if side.exists():
        os.replace(side, sidecar_path(dst))
    return dst


def uploads_dir(root: Path) -> Path:
    folder = root / UPLOADS_DIR
    ensure_dir(folder)
    return folder


def purge_old_files(root: Path) -> list[str]:
    """Remove abandoned uploads (> 1 day) and trash (> 30 days). Returns what went."""
    removed: list[str] = []
    now = time.time()
    uploads = root / UPLOADS_DIR
    if uploads.is_dir():
        for item in uploads.iterdir():
            with contextlib.suppress(OSError):
                if item.is_file() and now - item.stat().st_mtime > UPLOAD_MAX_AGE_SECONDS:
                    item.unlink()
                    removed.append(f"{UPLOADS_DIR}/{item.name}")
    trash = root / TRASH_DIR
    if trash.is_dir():
        for item in trash.iterdir():
            with contextlib.suppress(OSError):
                if now - item.stat().st_mtime > TRASH_MAX_AGE_SECONDS:
                    if item.is_dir():
                        shutil.rmtree(item)
                    else:
                        item.unlink()
                    removed.append(f"{TRASH_DIR}/{item.name}")
    return removed


@dataclass
class DiskUsage:
    total: int
    used: int
    free: int

    @property
    def percent_used(self) -> float:
        return 100.0 * self.used / self.total if self.total else 0.0


def disk_usage(root: Path) -> DiskUsage | None:
    try:
        usage = shutil.disk_usage(root)
    except OSError:
        return None
    return DiskUsage(usage.total, usage.used, usage.free)


def content_bytes(db: Session) -> int:
    from sqlalchemy import func, select

    return int(db.scalar(select(func.coalesce(func.sum(Content.file_size_bytes), 0))) or 0)
