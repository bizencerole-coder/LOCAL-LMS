"""Catalogue operations behind the dashboard, keeping folders and the database in step.

Each function changes the database (the caller commits) and the folders under the
content root. File changes happen under the catalogue lock, so they never race the
folder sync.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..fileinfo import ContentFileError, inspect_content_file
from ..media import is_valid_folder, slugify
from ..models import Batch, Content, ContentStatus, Module, SchoolClass, Student, Subject
from ..storage import (
    catalogue_lock,
    content_file_stem,
    ensure_dir,
    module_chain,
    module_dir,
    module_rel,
    move_file,
    move_to_trash,
    path_for_key,
    remove_folder_if_unused,
    unique_file_name,
    write_sidecar,
    write_title_file,
)
from .web import FormError


def clean_name(value: str | None, what: str, max_length: int = 200, required: bool = True) -> str:
    value = (value or "").strip()
    if required and not value:
        raise FormError(f"{what} is required.")
    if "\x00" in value:
        raise FormError(f"{what} contains characters that cannot be stored.")
    if len(value) > max_length:
        raise FormError(f"{what} must be at most {max_length} characters.")
    return value


def clean_text(value: str | None, max_length: int = 5000) -> str | None:
    value = (value or "").replace("\x00", "").strip()
    return value[:max_length] or None


def pick_folder(wanted: str | None, default_from: str, taken: set[str]) -> str:
    """A folder name not used by a sibling. An explicit name must be valid and free."""
    wanted = (wanted or "").strip()
    if wanted:
        if not is_valid_folder(wanted):
            raise FormError(
                f"Folder name {wanted!r} is not valid: use letters, digits, '.', '-' and '_' only, "
                "starting with a letter or digit (no spaces)."
            )
        if wanted in taken:
            raise FormError(f"Another item here already uses the folder {wanted!r}.")
        return wanted
    base = slugify(default_from)
    name, n = base, 2
    while name in taken:
        name = f"{base}-{n}"
        n += 1
    return name


def _next_order(db: Session, column, parent_column, parent_id) -> int:
    return int(db.scalar(select(func.coalesce(func.max(column), 0)).where(parent_column == parent_id)) or 0) + 1


# --------------------------------------------------------------------------- structure


def create_batch(db: Session, root: Path, name: str, folder: str | None, description: str | None) -> Batch:
    name = clean_name(name, "Batch name", 120)
    if db.scalar(select(Batch.id).where(Batch.name == name)):
        raise FormError(f"A batch called {name!r} already exists.")
    taken = set(db.scalars(select(Batch.folder)))
    batch = Batch(name=name, folder=pick_folder(folder, name, taken), description=clean_text(description))
    db.add(batch)
    db.flush()
    write_title_file(root / batch.folder, batch.name)
    return batch


def create_class(db: Session, root: Path, batch: Batch, name: str, folder: str | None, description: str | None) -> SchoolClass:
    name = clean_name(name, "Class name", 100)
    if db.scalar(select(SchoolClass.id).where(SchoolClass.batch_id == batch.id, SchoolClass.name == name)):
        raise FormError(f"{batch.name} already has a class called {name!r}.")
    taken = set(db.scalars(select(SchoolClass.folder).where(SchoolClass.batch_id == batch.id)))
    item = SchoolClass(
        batch_id=batch.id,
        name=name,
        folder=pick_folder(folder, name, taken),
        description=clean_text(description),
        sort_order=_next_order(db, SchoolClass.sort_order, SchoolClass.batch_id, batch.id),
    )
    db.add(item)
    db.flush()
    write_title_file(root / batch.folder / item.folder, item.name)
    return item


def create_subject(db: Session, root: Path, school_class: SchoolClass, name: str, folder: str | None,
                   description: str | None) -> Subject:
    name = clean_name(name, "Subject name", 150)
    if db.scalar(select(Subject.id).where(Subject.class_id == school_class.id, Subject.name == name)):
        raise FormError(f"{school_class.name} already has a subject called {name!r}.")
    taken = set(db.scalars(select(Subject.folder).where(Subject.class_id == school_class.id)))
    batch = db.get(Batch, school_class.batch_id)
    item = Subject(
        class_id=school_class.id,
        name=name,
        folder=pick_folder(folder, name, taken),
        description=clean_text(description),
        sort_order=_next_order(db, Subject.sort_order, Subject.class_id, school_class.id),
    )
    db.add(item)
    db.flush()
    write_title_file(root / batch.folder / school_class.folder / item.folder, item.name)
    return item


def create_module(db: Session, root: Path, subject: Subject, title: str, folder: str | None,
                  description: str | None, published: bool) -> Module:
    title = clean_name(title, "Module title")
    if db.scalar(select(Module.id).where(Module.subject_id == subject.id, Module.title == title)):
        raise FormError(f"{subject.name} already has a module called {title!r}.")
    taken = set(db.scalars(select(Module.folder).where(Module.subject_id == subject.id)))
    order = _next_order(db, Module.sort_order, Module.subject_id, subject.id)
    item = Module(
        subject_id=subject.id,
        title=title,
        folder=pick_folder(folder, f"{order:02d}-{title}", taken),
        description=clean_text(description),
        sort_order=order,
        is_published=published,
    )
    db.add(item)
    db.flush()
    write_title_file(module_dir(db, root, item), item.title)
    return item


def folder_path(db: Session, root: Path, item) -> Path:
    """The directory of a batch, class, subject or module."""
    if isinstance(item, Batch):
        return root / item.folder
    if isinstance(item, SchoolClass):
        return root / db.get(Batch, item.batch_id).folder / item.folder
    if isinstance(item, Subject):
        school_class = db.get(SchoolClass, item.class_id)
        return folder_path(db, root, school_class) / item.folder
    if isinstance(item, Module):
        return module_dir(db, root, item)
    raise TypeError(item)


def rename(db: Session, root: Path, item, new_name: str) -> None:
    """Change a display name; the folder stays. Updates the folder's title.txt."""
    folder = folder_path(db, root, item)
    if isinstance(item, Module) and not item.folder:
        return  # files directly in the subject folder: nothing to write
    write_title_file(folder, new_name)


def delete_structure(db: Session, root: Path, item) -> str:
    """Delete an empty batch/class/subject/module. Returns a note about its folder."""
    if isinstance(item, Batch):
        if db.scalar(select(func.count()).select_from(SchoolClass).where(SchoolClass.batch_id == item.id)):
            raise FormError("Delete or move this batch's classes first.")
    elif isinstance(item, SchoolClass):
        if db.scalar(select(func.count()).select_from(Subject).where(Subject.class_id == item.id)):
            raise FormError("Delete this class's subjects first.")
        if db.scalar(select(func.count()).select_from(Student).where(Student.class_id == item.id)):
            raise FormError("Students are assigned to this class. Move them to another class first.")
    elif isinstance(item, Subject):
        if db.scalar(select(func.count()).select_from(Module).where(Module.subject_id == item.id)):
            raise FormError("Delete this subject's modules first.")
    elif isinstance(item, Module):
        if db.scalar(select(func.count()).select_from(Content).where(Content.module_id == item.id)):
            raise FormError("Delete or move this module's content first.")
    catalogue_lock(db)
    folder = folder_path(db, root, item)
    db.delete(item)
    db.flush()
    if isinstance(item, Module) and not item.folder:
        return ""
    try:
        if remove_folder_if_unused(folder):
            return ""
    except OSError:
        pass
    return f" Its folder still holds other files, so it was kept: {folder.name}"


def reorder(db: Session, items: list, item, direction: str) -> None:
    """Move ``item`` one place up or down among ``items`` (already in display order)."""
    index = next(i for i, x in enumerate(items) if x.id == item.id)
    other = index - 1 if direction == "up" else index + 1
    if not 0 <= other < len(items):
        return
    items[index], items[other] = items[other], items[index]
    for position, x in enumerate(items, start=1):
        x.sort_order = position


# --------------------------------------------------------------------------- content


def file_problems(root: Path, content: Content) -> tuple[bool, list[str]]:
    """(file exists, problems found by inspecting it)."""
    path = path_for_key(root, content.storage_key)
    if not path.is_file():
        return False, ["The file is missing from the content folder."]
    try:
        return True, inspect_content_file(path, compute_checksum=False).problems
    except ContentFileError as exc:
        return True, [str(exc)]


def set_status(db: Session, root: Path, content: Content, status: ContentStatus, force: bool) -> None:
    if status is ContentStatus.PUBLISHED:
        exists, problems = file_problems(root, content)
        if not exists:
            raise FormError("Cannot publish: the file is missing from the content folder.")
        if problems and not force:
            raise FormError(
                "Not published: " + " ".join(problems) + " Fix the file, or use 'Publish anyway' on the item's page."
            )
    content.status = status.value


def update_content_text(root: Path, content: Content, title: str, description: str | None) -> None:
    content.title = clean_name(title, "Title")
    content.description = clean_text(description)
    path = path_for_key(root, content.storage_key)
    if path.is_file():
        write_sidecar(path, content.title, content.description)


def move_content(db: Session, root: Path, content: Content, target: Module) -> None:
    """File the item under another module: moves the file (and sidecar) and its key."""
    if target.id == content.module_id:
        return
    catalogue_lock(db)
    batch, school_class, subject = module_chain(db, target)
    target_dir = module_dir(db, root, target)
    ensure_dir(target_dir)
    order = _next_order(db, Content.sort_order, Content.module_id, target.id)
    ext = Path(content.storage_key).suffix.lower()
    name = unique_file_name(target_dir, content_file_stem(order, content.title), ext)
    new_key = f"{module_rel(batch, school_class, subject, target)}/{name}"
    src = path_for_key(root, content.storage_key)
    if src.exists():
        move_file(src, target_dir / name)
    content.storage_key = new_key
    content.module_id = target.id
    content.sort_order = order
    db.flush()


def delete_content(db: Session, root: Path, content: Content) -> Path | None:
    """Remove the item (progress goes with it); its file goes to .trash for 30 days."""
    catalogue_lock(db)
    trashed = move_to_trash(root, content.storage_key)
    db.delete(content)
    db.flush()
    return trashed


def next_content_order(db: Session, module: Module) -> int:
    return _next_order(db, Content.sort_order, Content.module_id, module.id)
