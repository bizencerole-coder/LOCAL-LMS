"""Folder sync: bring the catalogue in line with the files under VIDEO_ROOT.

Layout (names: letters, digits, '.', '-', '_'; each part starts with a letter or digit):

    <batch>/<class>/<subject>/<module>/<NN-name>.<mp4|m4v|pdf|jpg|jpeg|png|webp>
    <batch>/<class>/<subject>/<NN-name>.<ext>        -> module "General"

The batch folder must belong to a batch created in the dashboard (or the CLI); files
under unknown top-level folders are reported and skipped, so a file dropped at the wrong
depth never creates stray batches. Classes, subjects and modules are created from their
folders as needed. Display names come from the folder/file names: a leading "NN-" gives
the order and is dropped, '-' and '_' become spaces, words are capitalised, and a digit
after letters gets a space ("class12" -> "Class 12"). A ``title.txt`` inside a folder,
or a ``<name>.txt`` next to a file (first line title, rest description), overrides that.

A registered item follows its file: when a file is moved or renamed (same type and size,
plus the same duration for videos or the same checksum otherwise; one gone, one new)
the item keeps its row, status and students' progress and is re-filed by its new
folders. A replaced file gets fresh metadata. Gone files are archived only with
``archive_missing``, never when the whole library looks missing (storage not mounted).
"""

from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .fileinfo import ContentFileError, ContentFileInfo, inspect_content_file
from .media import InvalidStorageKey, content_type_for, validate_storage_key
from .models import (
    Batch,
    Content,
    ContentStatus,
    ContentType,
    Module,
    SchoolClass,
    Subject,
    SyncRun,
    utcnow,
)
from .storage import TITLE_FILE, catalogue_lock, purge_old_files, sidecar_path

ROOT_MODULE_TITLE = "General"
_ORDER_PREFIX_RE = re.compile(r"^(\d{1,3})[-_. ]+(.+)$")
_REPORT_LIMIT = 20000


def display_name(segment: str) -> tuple[int | None, str]:
    """'02-python-functions' -> (2, 'Python Functions'); 'class12' -> (None, 'Class 12')."""
    order: int | None = None
    match = _ORDER_PREFIX_RE.match(segment)
    if match:
        order, segment = int(match.group(1)), match.group(2)
    name = re.sub(r"[-_]+", " ", segment).strip()
    name = re.sub(r"(?<=[A-Za-z])(?=\d)", " ", name)
    name = " ".join(word[:1].upper() + word[1:] for word in name.split())
    return order, name


def first_line(path: Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                return line.strip()
    except (OSError, UnicodeDecodeError):
        return None
    return None


def folder_title(folder: Path, derived: str) -> str:
    override = first_line(folder / TITLE_FILE) if (folder / TITLE_FILE).is_file() else None
    return (override or derived)[:200]


def read_sidecar(file_path: Path) -> tuple[str | None, str | None]:
    """Title and description from ``<name>.txt`` next to the file, if present."""
    side = sidecar_path(file_path)
    if not side.is_file():
        return None, None
    try:
        lines = side.read_text(encoding="utf-8").strip().splitlines()
    except (OSError, UnicodeDecodeError):
        return None, None
    title = lines[0].strip()[:200] if lines else None
    description = "\n".join(line.rstrip() for line in lines[1:]).strip() or None
    return (title or None), description


@dataclass
class SyncResult:
    lines: list[str] = field(default_factory=list)
    registered: int = 0
    moved: int = 0
    updated: int = 0
    archived: int = 0
    skipped: int = 0
    failed: int = 0
    problems: int = 0
    already: int = 0
    removed_modules: int = 0
    published: bool = False

    def add(self, line: str) -> None:
        self.lines.append(line)

    @property
    def summary(self) -> str:
        return (
            f"Sync complete: {self.registered} item(s) registered"
            f"{' and published' if self.published else ' as draft'}, "
            f"{self.moved} moved, {self.updated} updated, {self.already} already registered, "
            f"{self.skipped} skipped, {self.problems} with problems, {self.archived} archived, "
            f"{self.removed_modules} empty module(s) removed."
        )

    @property
    def report(self) -> str:
        return "\n".join([*self.lines, self.summary])


class _NewFile(NamedTuple):
    key: str
    path: Path
    info: ContentFileInfo


def _fingerprint_row(content: Content) -> tuple:
    if content.content_type == ContentType.VIDEO.value:
        return (content.content_type, content.file_size_bytes, content.duration_seconds)
    return (content.content_type, content.file_size_bytes, content.checksum)


def _fingerprint_file(info: ContentFileInfo) -> tuple:
    if info.content_type is ContentType.VIDEO:
        return (info.content_type.value, info.size_bytes, info.duration_seconds)
    return (info.content_type.value, info.size_bytes, info.checksum)


class _Catalogue:
    """Finds or creates classes, subjects and modules from folder names."""

    def __init__(self, db: Session, root: Path, result: SyncResult) -> None:
        self.db = db
        self.root = root
        self.result = result

    def _unique_name(self, model, parent_col, parent_id, name_col, wanted: str, folder: str) -> str:
        exists = self.db.scalar(select(model.id).where(parent_col == parent_id, name_col == wanted))
        return wanted if exists is None else f"{wanted} ({folder})"[:200]

    def module_for(self, batch: Batch, parts: list[str]) -> Module:
        class_folder, subject_folder = parts[1], parts[2]
        module_folder = parts[3] if len(parts) == 5 else ""
        batch_dir = self.root / batch.folder

        school_class = self.db.scalar(
            select(SchoolClass).where(SchoolClass.batch_id == batch.id, SchoolClass.folder == class_folder)
        )
        if school_class is None:
            name = folder_title(batch_dir / class_folder, display_name(class_folder)[1])
            name = self._unique_name(SchoolClass, SchoolClass.batch_id, batch.id, SchoolClass.name, name, class_folder)
            school_class = SchoolClass(batch_id=batch.id, name=name[:100], folder=class_folder, is_active=True)
            self.db.add(school_class)
            self.db.flush()
            self.result.add(f"+ class {batch.name} / {school_class.name}")

        subject = self.db.scalar(
            select(Subject).where(Subject.class_id == school_class.id, Subject.folder == subject_folder)
        )
        if subject is None:
            order, derived = display_name(subject_folder)
            name = folder_title(batch_dir / class_folder / subject_folder, derived)
            name = self._unique_name(Subject, Subject.class_id, school_class.id, Subject.name, name, subject_folder)
            subject = Subject(
                class_id=school_class.id, name=name[:150], folder=subject_folder, sort_order=order or 0, is_active=True
            )
            self.db.add(subject)
            self.db.flush()
            self.result.add(f"+ subject {school_class.name} / {subject.name}")

        module = self.db.scalar(
            select(Module).where(Module.subject_id == subject.id, Module.folder == module_folder)
        )
        if module is None:
            if module_folder:
                order, derived = display_name(module_folder)
                title = folder_title(batch_dir / class_folder / subject_folder / module_folder, derived)
            else:
                order, title = 0, ROOT_MODULE_TITLE
            title = self._unique_name(Module, Module.subject_id, subject.id, Module.title, title, module_folder or "root")
            module = Module(
                subject_id=subject.id, title=title, folder=module_folder, sort_order=order or 0, is_published=True
            )
            self.db.add(module)
            self.db.flush()
            self.result.add(f"+ module {subject.name} / {module.title}")
        return module

    def label(self, module: Module) -> str:
        subject = self.db.get(Subject, module.subject_id)
        school_class = self.db.get(SchoolClass, subject.class_id)
        return f"{school_class.name} / {subject.name} / {module.title}"


def _walk(root: Path):
    """Yield content-looking files under ``root``, skipping hidden/system folders."""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d[:1].isalnum())
        for name in sorted(filenames):
            if not name[:1].isalnum() or content_type_for(name) is None:
                continue
            yield Path(dirpath) / name


def sync_catalogue(
    db: Session,
    root: Path,
    *,
    publish: bool,
    archive_missing: bool,
    allow_mass_archive: bool = False,
) -> SyncResult:
    """Register, re-file and (optionally) archive content from the folders. Re-runnable.

    The caller commits. Holds the catalogue lock until then.
    """
    catalogue_lock(db)
    result = SyncResult(published=publish)
    catalogue = _Catalogue(db, root, result)
    batches = {b.folder: b for b in db.scalars(select(Batch))}
    registered = {c.storage_key: c for c in db.scalars(select(Content))}
    seen: set[str] = set()
    new_files: list[_NewFile] = []
    unknown_batches: dict[str, int] = {}

    if not root.is_dir():
        result.add(f"WARNING: content folder {root} does not exist; nothing to do.")
        result.problems += 1
        return result

    for path in _walk(root):
        key = path.relative_to(root).as_posix()
        try:
            validate_storage_key(key)
        except InvalidStorageKey:
            result.add(f"skip  {key}: rename it using only letters, digits, '.', '-' and '_' (no spaces)")
            result.skipped += 1
            continue
        parts = key.split("/")
        if len(parts) == 1:
            result.add(f"skip  {key}: files directly in the content folder are not used; put it in a module folder")
            result.skipped += 1
            continue
        if parts[0] not in batches:
            unknown_batches[parts[0]] = unknown_batches.get(parts[0], 0) + 1
            result.skipped += 1
            continue
        if not 4 <= len(parts) <= 5:
            result.add(f"skip  {key}: expected <batch>/<class>/<subject>/[<module>/]<file>")
            result.skipped += 1
            continue
        seen.add(key)
        content = registered.get(key)
        if content is not None and content.file_size_bytes == path.stat().st_size:
            result.already += 1
            continue
        try:
            info = inspect_content_file(path)
        except ContentFileError as exc:
            result.add(f"FAIL  {key}: {exc}")
            result.failed += 1
            result.problems += 1
            continue
        if content is None:
            new_files.append(_NewFile(key, path, info))
            continue
        # The file was replaced (or has finished copying): refresh what the app shows.
        for column, value in info.metadata().items():
            setattr(content, column, value)
        result.updated += 1
        result.add(f"~ updated {key} (file changed: {info.size_bytes} bytes)")
        for problem in info.problems:
            result.problems += 1
            result.add(f"      WARNING: {problem}")

    for folder, count in sorted(unknown_batches.items()):
        result.add(
            f"skip  {folder}/...: {count} file(s) in a folder that is not a batch. Create the batch in the "
            "dashboard (its folder name is shown there) or move the files into a batch folder."
        )

    missing = [c for k, c in registered.items() if k not in seen and c.status != ContentStatus.ARCHIVED.value]
    emptied: set[uuid.UUID] = set()
    if missing and new_files:
        gone: dict[tuple, list[Content]] = {}
        for content in missing:
            gone.setdefault(_fingerprint_row(content), []).append(content)
        arrived: dict[tuple, list[_NewFile]] = {}
        for entry in new_files:
            arrived.setdefault(_fingerprint_file(entry.info), []).append(entry)
        for fingerprint, old_items in gone.items():
            candidates = arrived.get(fingerprint, [])
            if len(old_items) != 1 or len(candidates) != 1:
                continue  # nothing to tell them apart: treat as new files (and removals)
            content, entry = old_items[0], candidates[0]
            old_key, old_module_id = content.storage_key, content.module_id
            parts = entry.key.split("/")
            module = catalogue.module_for(batches[parts[0]], parts)
            content.module_id = module.id
            if module.id != old_module_id:
                emptied.add(old_module_id)
            title, description = read_sidecar(entry.path)
            order, derived = display_name(entry.path.stem)
            if title:
                content.title, content.description = title, description
            elif content.title == display_name(Path(old_key).stem)[1]:
                content.title = derived  # an automatic name follows the file name
            if order is not None:
                content.sort_order = order
            for column, value in entry.info.metadata().items():
                setattr(content, column, value)
            content.storage_key = entry.key
            db.flush()
            missing.remove(content)
            new_files.remove(entry)
            result.moved += 1
            result.add(f"~ moved {old_key} -> {entry.key}  [{content.status}] {catalogue.label(module)} / {content.title}")

    for entry in new_files:
        parts = entry.key.split("/")
        module = catalogue.module_for(batches[parts[0]], parts)
        title, description = read_sidecar(entry.path)
        order, derived = display_name(entry.path.stem)
        status = ContentStatus.PUBLISHED if (publish and not entry.info.problems) else ContentStatus.DRAFT
        content = Content(
            module_id=module.id,
            title=title or derived or entry.path.stem,
            description=description,
            storage_key=entry.key,
            sort_order=order or 0,
            status=status.value,
            **entry.info.metadata(),
        )
        db.add(content)
        db.flush()
        result.registered += 1
        result.add(f"+ [{status.value}] {catalogue.label(module)} / {content.title}  ({entry.key})")
        for problem in entry.info.problems:
            result.problems += 1
            result.add(f"      WARNING: {problem}")

    # A module whose last item was moved away disappears with it (it comes back from the
    # folder as soon as a file is placed there again).
    for module_id in emptied:
        if db.scalar(select(func.count()).select_from(Content).where(Content.module_id == module_id)):
            continue
        module = db.get(Module, module_id)
        if module is not None:
            subject = db.get(Subject, module.subject_id)
            result.add(f"- removed empty module {subject.name} / {module.title}")
            db.delete(module)
            result.removed_modules += 1
    db.flush()

    if archive_missing and missing:
        active = sum(1 for c in registered.values() if c.status != ContentStatus.ARCHIVED.value)
        if not seen:
            result.add("WARNING: no content files found under the content folder; nothing archived (is the storage mounted?)")
            result.problems += 1
        elif len(missing) > max(5, active // 2) and not allow_mass_archive:
            result.add(
                f"WARNING: {len(missing)} of {active} items have no file; nothing archived. If they were removed "
                "on purpose, archive them in the dashboard or run sync with --allow-mass-archive."
            )
            result.problems += 1
        else:
            for content in missing:
                content.status = ContentStatus.ARCHIVED.value
                result.archived += 1
                result.add(f"- archived {content.storage_key} (file not found)")

    for item in purge_old_files(root):
        result.add(f"- purged {item}")
    return result


def record_sync_run(db: Session, result: SyncResult, trigger: str, staff_id: uuid.UUID | None = None) -> SyncRun:
    report = result.report
    if len(report) > _REPORT_LIMIT:
        report = report[: _REPORT_LIMIT - 40] + "\n... (report truncated)"
    run = SyncRun(
        trigger=trigger,
        staff_id=staff_id,
        finished_at=utcnow(),
        registered=result.registered,
        moved=result.moved,
        updated=result.updated,
        archived=result.archived,
        skipped=result.skipped,
        problems=result.problems,
        report=report,
    )
    db.add(run)
    db.flush()
    # Keep the last 200 runs.
    old = db.scalars(select(SyncRun.id).order_by(SyncRun.started_at.desc()).offset(200)).all()
    if old:
        from sqlalchemy import delete

        db.execute(delete(SyncRun).where(SyncRun.id.in_(old)))
    return run


def relocate_legacy_layout(db: Session, root: Path, apply: bool) -> list[str]:
    """Move folders of the pre-batch layout (<class>/<subject>/...) into their batch folder.

    Used once after the upgrade that introduced batches: the database migration prefixed
    every storage key with the default batch's folder; this moves the files to match.
    Idempotent. Returns what was (or, without ``apply``, would be) done. Holds the catalogue
    lock until the caller commits, so a folder sync started meanwhile (cron) waits instead
    of seeing half-moved files and archiving the rest.
    """
    if apply:
        catalogue_lock(db)
    lines: list[str] = []
    moves: dict[str, str] = {}  # legacy top-level folder -> batch folder
    for key in db.scalars(select(Content.storage_key)):
        batch_folder, _, legacy_key = key.partition("/")
        if not legacy_key or (root / key).exists():
            continue
        legacy_top = legacy_key.split("/")[0]
        if (root.joinpath(*legacy_key.split("/"))).exists():
            moves.setdefault(legacy_top, batch_folder)
    for legacy_top, batch_folder in sorted(moves.items()):
        src, dst = root / legacy_top, root / batch_folder / legacy_top
        lines.append(f"{'move' if apply else 'would move'} {legacy_top}/ -> {batch_folder}/{legacy_top}/")
        if not apply:
            continue
        # File by file (some bind mounts refuse to rename folders), keeping anything
        # already in place from an earlier, interrupted run; then drop the empty folders.
        for dirpath, _dirs, files in os.walk(src, topdown=False):
            rel = Path(dirpath).relative_to(src)
            for name in files:
                target = dst / rel / name
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(Path(dirpath) / name, target)
            try:
                Path(dirpath).rmdir()
            except OSError:
                pass
    return lines
