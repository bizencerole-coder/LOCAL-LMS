"""Server-side administration: the same operations as the web dashboard, for the shell.

Run inside the API container (deploy/scripts/lms-admin.sh wraps this), e.g.:

    python -m app.cli tree
    python -m app.cli create-staff --username principal --name "Principal" --role admin
    python -m app.cli sync-videos --publish --archive-missing

Passwords are never accepted as command-line arguments: they are prompted for, or read
with --password-stdin / --password-env.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from .catalog_sync import record_sync_run, relocate_legacy_layout, sync_catalogue
from .config import get_settings
from .db import session_scope
from .fileinfo import ContentFileError, ContentFileInfo, inspect_content_file
from .media import (
    ALLOWED_EXTENSIONS,
    InvalidStorageKey,
    content_type_for,
    is_valid_folder,
    resolve_media_path,
    slugify,
    validate_storage_key,
)
from .models import (
    AuthSession,
    LoginThrottle,
    Batch,
    Content,
    ContentStatus,
    Module,
    SchoolClass,
    StaffRole,
    StaffSession,
    StaffUser,
    Student,
    Subject,
    utcnow,
)
from .mp4info import report
from .security import MIN_PASSWORD_LENGTH, hash_password

DEFAULT_MANIFEST = Path(__file__).resolve().parent.parent / "seed" / "demo_catalog.json"


class CliError(Exception):
    pass


# --------------------------------------------------------------------------- lookups


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _check_name(value: str, what: str, max_length: int = 200) -> str:
    value = value.strip()
    if not value:
        raise CliError(f"{what} must not be empty.")
    if "/" in value:
        raise CliError(f"{what} must not contain '/': {value!r}")
    if len(value) > max_length:
        raise CliError(f"{what} must be at most {max_length} characters.")
    return value


def _check_folder(value: str | None, default_from: str) -> str:
    folder = value.strip() if value else slugify(default_from)
    if not is_valid_folder(folder):
        raise CliError(
            f"Folder name {folder!r} is not valid: use letters, digits, '.', '-' and '_' "
            "only, starting with a letter or digit."
        )
    return folder


def find_batch(db: Session, ref: str) -> Batch:
    """By ID, name or folder."""
    ref_id = _as_uuid(ref)
    if ref_id:
        found = db.get(Batch, ref_id)
    else:
        found = db.scalar(select(Batch).where(or_(Batch.name == ref.strip(), Batch.folder == ref.strip())))
    if found is None:
        raise CliError(f"Batch not found: {ref}")
    return found


def find_class(db: Session, ref: str) -> SchoolClass:
    """By ID, "Batch/Class", or a class name that is unique across batches."""
    ref_id = _as_uuid(ref)
    if ref_id:
        found = db.get(SchoolClass, ref_id)
        if found is None:
            raise CliError(f"Class not found: {ref}")
        return found
    parts = [p.strip() for p in ref.split("/")]
    if len(parts) == 2:
        batch = find_batch(db, parts[0])
        found = db.scalar(
            select(SchoolClass).where(
                SchoolClass.batch_id == batch.id,
                or_(SchoolClass.name == parts[1], SchoolClass.folder == parts[1]),
            )
        )
        if found is None:
            raise CliError(f"Class not found: {ref}")
        return found
    if len(parts) != 1:
        raise CliError(f'Class reference must be an ID, "Batch/Class" or a class name: {ref}')
    matches = db.scalars(select(SchoolClass).where(SchoolClass.name == parts[0])).all()
    if not matches:
        raise CliError(f"Class not found: {ref}")
    if len(matches) > 1:
        names = ", ".join(f'"{class_label(db, c)}"' for c in matches)
        raise CliError(f"More than one class is called {ref!r}; use one of: {names}")
    return matches[0]


def find_subject(db: Session, ref: str) -> Subject:
    """By ID, "Class/Subject" or "Batch/Class/Subject"."""
    ref_id = _as_uuid(ref)
    if ref_id:
        found = db.get(Subject, ref_id)
    else:
        parts = [p.strip() for p in ref.split("/")]
        if len(parts) not in (2, 3):
            raise CliError(f'Subject reference must be an ID or "[Batch/]Class/Subject": {ref}')
        school_class = find_class(db, "/".join(parts[:-1]))
        found = db.scalar(
            select(Subject).where(
                Subject.class_id == school_class.id, or_(Subject.name == parts[-1], Subject.folder == parts[-1])
            )
        )
    if found is None:
        raise CliError(f"Subject not found: {ref}")
    return found


def find_module(db: Session, ref: str) -> Module:
    """By ID, "Class/Subject/Module" or "Batch/Class/Subject/Module"."""
    ref_id = _as_uuid(ref)
    if ref_id:
        found = db.get(Module, ref_id)
    else:
        parts = [p.strip() for p in ref.split("/")]
        if len(parts) not in (3, 4):
            raise CliError(f'Module reference must be an ID or "[Batch/]Class/Subject/Module": {ref}')
        subject = find_subject(db, "/".join(parts[:-1]))
        found = db.scalar(
            select(Module).where(Module.subject_id == subject.id, or_(Module.title == parts[-1], Module.folder == parts[-1]))
        )
    if found is None:
        raise CliError(f"Module not found: {ref}")
    return found


def find_content(db: Session, ref: str) -> Content:
    """By ID or storage key."""
    ref_id = _as_uuid(ref)
    found = (
        db.get(Content, ref_id)
        if ref_id
        else db.scalar(select(Content).where(Content.storage_key == ref.strip()))
    )
    if found is None:
        raise CliError(f"Content not found: {ref}")
    return found


def find_student(db: Session, ref: str) -> Student:
    """By username, student code or ID."""
    ref_id = _as_uuid(ref)
    if ref_id:
        found = db.get(Student, ref_id)
    else:
        found = db.scalar(
            select(Student).where(
                or_(Student.username == ref.strip().lower(), Student.student_code == ref.strip().upper())
            )
        )
    if found is None:
        raise CliError(f"Student not found: {ref}")
    return found


def find_staff(db: Session, ref: str) -> StaffUser:
    ref_id = _as_uuid(ref)
    found = (
        db.get(StaffUser, ref_id)
        if ref_id
        else db.scalar(select(StaffUser).where(StaffUser.username == ref.strip().lower()))
    )
    if found is None:
        raise CliError(f"Staff account not found: {ref}")
    return found


def class_label(db: Session, school_class: SchoolClass) -> str:
    batch = db.get(Batch, school_class.batch_id)
    return f"{batch.name}/{school_class.name}"


# --------------------------------------------------------------------------- helpers


def read_password(args: argparse.Namespace, prompt: str = "Password: ") -> str:
    if getattr(args, "password_stdin", False):
        password = sys.stdin.readline().rstrip("\r\n")
    elif getattr(args, "password_env", None):
        password = os.environ.get(args.password_env, "")
        if not password:
            raise CliError(f"Environment variable {args.password_env} is empty or not set.")
    else:
        password = getpass.getpass(prompt)
        if password != getpass.getpass("Repeat password: "):
            raise CliError("Passwords do not match.")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise CliError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    return password


def revoke_sessions(db: Session, student: Student) -> int:
    result = db.execute(
        update(AuthSession)
        .where(AuthSession.student_id == student.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    return result.rowcount or 0


def revoke_staff_sessions(db: Session, staff: StaffUser) -> int:
    result = db.execute(
        update(StaffSession)
        .where(StaffSession.staff_id == staff.id, StaffSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    return result.rowcount or 0


def inspect_content(storage_key: str) -> tuple[Path, ContentFileInfo]:
    """Validate the key, check the file, and extract metadata. CliError if unusable."""
    try:
        key = validate_storage_key(storage_key)
    except InvalidStorageKey as exc:
        raise CliError(str(exc)) from exc
    path = resolve_media_path(get_settings().video_root, key)
    try:
        return path, inspect_content_file(path)
    except ContentFileError as exc:
        raise CliError(str(exc)) from exc


def fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return "--:--"
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _single_batch_or(db: Session, ref: str | None) -> Batch:
    if ref:
        return find_batch(db, ref)
    batches = db.scalars(select(Batch)).all()
    if len(batches) == 1:
        return batches[0]
    raise CliError("Give the batch with --batch (there is more than one, or none yet: create-batch).")


# --------------------------------------------------------------------------- structure


def cmd_create_batch(db: Session, args: argparse.Namespace) -> None:
    name = _check_name(args.name, "Batch name", 120)
    batch = Batch(name=name, folder=_check_folder(args.folder, name), description=args.description)
    db.add(batch)
    db.flush()
    print(f"Created batch {batch.name} (folder {batch.folder}) id={batch.id}")


def cmd_create_class(db: Session, args: argparse.Namespace) -> None:
    batch = _single_batch_or(db, args.batch)
    name = _check_name(args.name, "Class name", 100)
    item = SchoolClass(
        batch_id=batch.id, name=name, folder=_check_folder(args.folder, name), description=args.description
    )
    db.add(item)
    db.flush()
    print(f"Created class {batch.name}/{item.name} (folder {item.folder}) id={item.id}")


def cmd_create_subject(db: Session, args: argparse.Namespace) -> None:
    school_class = find_class(db, args.class_ref)
    name = _check_name(args.name, "Subject name", 150)
    item = Subject(
        class_id=school_class.id, name=name, folder=_check_folder(args.folder, name), sort_order=args.sort
    )
    db.add(item)
    db.flush()
    print(f"Created subject {school_class.name}/{item.name} (folder {item.folder}) id={item.id}")


def cmd_create_module(db: Session, args: argparse.Namespace) -> None:
    subject = find_subject(db, args.subject)
    title = _check_name(args.title, "Module title")
    item = Module(
        subject_id=subject.id,
        title=title,
        folder=_check_folder(args.folder, f"{args.sort:02d}-{title}" if args.sort else title),
        description=args.description,
        sort_order=args.sort,
        is_published=args.publish,
    )
    db.add(item)
    db.flush()
    state = "published" if item.is_published else "unpublished"
    print(f"Created {state} module {item.title} (folder {item.folder}) id={item.id}")


def cmd_set_module_published(db: Session, args: argparse.Namespace) -> None:
    module = find_module(db, args.module)
    module.is_published = args.publish_value
    print(f"Module {module.title}: {'published' if module.is_published else 'unpublished'}")


# --------------------------------------------------------------------------- students


def cmd_create_student(db: Session, args: argparse.Namespace) -> None:
    school_class = find_class(db, args.class_ref) if args.class_ref else None
    password = read_password(args)
    student = Student(
        student_code=args.code.strip().upper(),
        username=args.username.strip().lower(),
        full_name=args.name.strip(),
        password_hash=hash_password(password),
        class_id=school_class.id if school_class else None,
        is_active=True,
    )
    db.add(student)
    db.flush()
    print(f"Created student {student.username} ({student.student_code}) id={student.id}")


def cmd_set_password(db: Session, args: argparse.Namespace) -> None:
    student = find_student(db, args.student)
    student.password_hash = hash_password(read_password(args, f"New password for {student.username}: "))
    revoked = revoke_sessions(db, student)
    db.execute(delete(LoginThrottle).where(LoginThrottle.key == f"student:{student.id}"))  # lifts a lock
    print(f"Password updated for {student.username}; {revoked} session(s) signed out.")


def cmd_set_student_active(db: Session, args: argparse.Namespace) -> None:
    student = find_student(db, args.student)
    student.is_active = args.active_value
    revoked = 0 if student.is_active else revoke_sessions(db, student)
    state = "active" if student.is_active else f"inactive ({revoked} session(s) signed out)"
    print(f"Student {student.username}: {state}")


def cmd_assign_class(db: Session, args: argparse.Namespace) -> None:
    student = find_student(db, args.student)
    school_class = find_class(db, args.class_ref)
    student.class_id = school_class.id
    print(f"Student {student.username} assigned to {class_label(db, school_class)}")


def cmd_list_students(db: Session, args: argparse.Namespace) -> None:
    rows = db.execute(
        select(Student, SchoolClass.name, Batch.name)
        .outerjoin(SchoolClass, Student.class_id == SchoolClass.id)
        .outerjoin(Batch, SchoolClass.batch_id == Batch.id)
        .order_by(Batch.name, SchoolClass.name, Student.username)
    ).all()
    for student, class_name, batch_name in rows:
        flag = "" if student.is_active else "  [inactive]"
        where = f"{batch_name}/{class_name}" if class_name else "-"
        print(f"{student.username:<24} {student.student_code:<16} {where:<28} {student.id}  {student.full_name}{flag}")
    print(f"{len(rows)} student(s)")


def _load_student_names(prefix: str, index: int) -> tuple[str, str]:
    return f"{prefix}{index:03d}", f"{prefix.upper()}-{index:03d}"


def cmd_create_load_students(db: Session, args: argparse.Namespace) -> None:
    """Students load001..loadNNN for deploy/scripts/load_test.py. Re-runnable."""
    if not re.fullmatch(r"[a-z][a-z0-9]{1,20}", args.prefix):
        raise CliError("--prefix must be 2-21 lower-case letters/digits (default: load)")
    if not 1 <= args.count <= 999:
        raise CliError("--count must be 1-999")
    school_class = find_class(db, args.class_ref)
    password_hash = hash_password(read_password(args, "Password for load-test students: "))
    existing = set(db.scalars(select(Student.username).where(Student.username.like(f"{args.prefix}___"))))
    created = 0
    for index in range(1, args.count + 1):
        username, code = _load_student_names(args.prefix, index)
        if username in existing:
            continue
        db.add(
            Student(
                student_code=code,
                username=username,
                full_name=f"Load Test {index}",
                password_hash=password_hash,
                class_id=school_class.id,
                is_active=True,
            )
        )
        created += 1
    db.flush()
    print(
        f"Created {created} load-test student(s); {args.prefix}001..{args.prefix}{args.count:03d} "
        f"exist in {school_class.name}"
    )


def cmd_delete_load_students(db: Session, args: argparse.Namespace) -> None:
    """Delete load-test students (sessions and progress go with them)."""
    result = db.execute(
        delete(Student).where(
            Student.username.like(f"{args.prefix}___"),
            Student.student_code.like(f"{args.prefix.upper()}-___"),
        )
    )
    print(f"Deleted {result.rowcount or 0} load-test student(s) with prefix {args.prefix!r}")


# --------------------------------------------------------------------------- staff


def cmd_create_staff(db: Session, args: argparse.Namespace) -> None:
    username = args.username.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,99}", username):
        raise CliError("Username: 2-100 characters, lower-case letters, digits, '.', '-', '_'.")
    if db.scalar(select(StaffUser.id).where(StaffUser.username == username)):
        raise CliError(f"A staff account called {username!r} already exists (use set-staff-password).")
    password = read_password(args, f"Password for {username}: ")
    staff = StaffUser(
        username=username,
        full_name=_check_name(args.name, "Name"),
        password_hash=hash_password(password),
        role=args.role,
        is_active=True,
    )
    db.add(staff)
    db.flush()
    print(f"Created {staff.role} account {staff.username} for the dashboard (/admin)")


def cmd_set_staff_password(db: Session, args: argparse.Namespace) -> None:
    staff = find_staff(db, args.staff)
    staff.password_hash = hash_password(read_password(args, f"New password for {staff.username}: "))
    revoked = revoke_staff_sessions(db, staff)
    print(f"Password updated for {staff.username}; {revoked} dashboard session(s) signed out.")


def cmd_set_staff_active(db: Session, args: argparse.Namespace) -> None:
    staff = find_staff(db, args.staff)
    staff.is_active = args.active_value
    revoked = 0 if staff.is_active else revoke_staff_sessions(db, staff)
    print(f"Staff {staff.username}: {'active' if staff.is_active else f'inactive ({revoked} session(s) signed out)'}")


def cmd_list_staff(db: Session, args: argparse.Namespace) -> None:
    rows = db.scalars(select(StaffUser).order_by(StaffUser.username)).all()
    for staff in rows:
        flag = "" if staff.is_active else "  [inactive]"
        print(f"{staff.username:<24} {staff.role:<6} {staff.full_name}{flag}")
    print(f"{len(rows)} staff account(s)")


# --------------------------------------------------------------------------- content


def cmd_add_content(db: Session, args: argparse.Namespace) -> None:
    module = find_module(db, args.module)
    path, info = inspect_content(args.storage_key)
    key = validate_storage_key(args.storage_key)
    if db.scalar(select(Content.id).where(Content.storage_key == key)):
        raise CliError(f"Content is already registered for {key}")
    content = Content(
        module_id=module.id,
        title=_check_name(args.title, "Title"),
        description=args.description,
        storage_key=key,
        sort_order=args.sort,
        status=ContentStatus.DRAFT.value,
        **info.metadata(),
    )
    db.add(content)
    db.flush()
    print(f"Registered draft {content.content_type} {content.title} ({content.id})")
    print(f"  file: {path}  size: {info.size_bytes / 1e6:.1f} MB  duration: {fmt_duration(info.duration_seconds)}")
    for problem in info.problems:
        print(f"  WARNING: {problem}")
    print("Check it, then run: python -m app.cli publish-content " + str(content.id))


def cmd_set_content_status(db: Session, args: argparse.Namespace) -> None:
    content = find_content(db, args.content)
    status = ContentStatus(args.status_value)
    if status is ContentStatus.PUBLISHED and not args.force:
        _, info = inspect_content(content.storage_key)
        if info.problems:
            raise CliError(
                "Not publishing; the file has problems:\n  - " + "\n  - ".join(info.problems)
                + "\nFix the file, or pass --force to publish anyway."
            )
        for column, value in info.metadata().items():
            setattr(content, column, value)
    content.status = status.value
    print(f"{content.content_type} {content.title}: {status.value}")
    if status is not ContentStatus.PUBLISHED:
        ttl = get_settings().playback_url_ttl_seconds
        print(f"  Note: links already issued stay valid for up to {ttl // 60} minutes.")


def cmd_check_media(db: Session, args: argparse.Namespace) -> int:
    items = db.scalars(select(Content).order_by(Content.storage_key)).all()
    failures = 0
    for content in items:
        try:
            _, info = inspect_content(content.storage_key)
        except CliError as exc:
            failures += 1
            print(f"FAIL  {content.status:<9} {content.storage_key}: {exc}")
            continue
        problems = list(info.problems)
        if content.file_size_bytes and info.size_bytes != content.file_size_bytes:
            problems.append(f"size changed since registration ({content.file_size_bytes} -> {info.size_bytes} bytes)")
        if args.update:
            for column, value in info.metadata().items():
                setattr(content, column, value)
        label = "WARN" if problems else "OK"
        print(f"{label:<5} {content.status:<9} {content.storage_key}  {fmt_duration(info.duration_seconds)}")
        for problem in problems:
            print(f"      - {problem}")
    print(f"{len(items)} item(s) checked, {failures} missing or unreadable")
    return 1 if failures else 0


def cmd_scan_videos(db: Session, args: argparse.Namespace) -> None:
    root = get_settings().video_root
    registered = set(db.scalars(select(Content.storage_key)))
    found = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or content_type_for(path.name) is None:
            continue
        key = path.relative_to(root).as_posix()
        if key in registered or any(part.startswith(".") for part in key.split("/")):
            continue
        found += 1
        try:
            validate_storage_key(key)
            print(f"unregistered  {key}")
        except InvalidStorageKey:
            print(f"bad-name      {key}  (rename: letters, digits, '.', '-', '_' only)")
    print(f"{found} unregistered file(s) under {root}")


def cmd_tree(db: Session, args: argparse.Namespace) -> None:
    for batch in db.scalars(select(Batch).order_by(Batch.sort_order, Batch.name)):
        flag = "" if batch.is_active else " [inactive]"
        print(f"{batch.name}{flag}  folder={batch.folder}  id={batch.id}")
        for school_class in db.scalars(
            select(SchoolClass).where(SchoolClass.batch_id == batch.id).order_by(SchoolClass.sort_order, SchoolClass.name)
        ):
            students = db.scalar(select(func.count(Student.id)).where(Student.class_id == school_class.id))
            flag = "" if school_class.is_active else " [inactive]"
            print(f"  {school_class.name}{flag}  ({students} students)  folder={school_class.folder}  id={school_class.id}")
            for subject in db.scalars(
                select(Subject).where(Subject.class_id == school_class.id).order_by(Subject.sort_order, Subject.name)
            ):
                flag = "" if subject.is_active else " [inactive]"
                print(f"    {subject.name}{flag}  folder={subject.folder}  id={subject.id}")
                for module in db.scalars(
                    select(Module).where(Module.subject_id == subject.id).order_by(Module.sort_order, Module.title)
                ):
                    flag = "" if module.is_published else " [unpublished]"
                    print(f"      {module.title}{flag}  folder={module.folder or '(subject folder)'}  id={module.id}")
                    for content in db.scalars(
                        select(Content).where(Content.module_id == module.id).order_by(Content.sort_order, Content.title)
                    ):
                        length = fmt_duration(content.duration_seconds) if content.is_video else content.content_type
                        print(
                            f"        [{content.status}] {content.title}  {length}  "
                            f"{content.storage_key}  id={content.id}"
                        )


def cmd_purge_sessions(db: Session, args: argparse.Namespace) -> None:
    cutoff = utcnow() - timedelta(days=1)
    students = db.execute(
        delete(AuthSession).where(or_(AuthSession.expires_at <= utcnow(), AuthSession.revoked_at <= cutoff))
    )
    staff = db.execute(
        delete(StaffSession).where(or_(StaffSession.expires_at <= utcnow(), StaffSession.revoked_at <= cutoff))
    )
    print(f"Deleted {students.rowcount or 0} student and {staff.rowcount or 0} staff expired/revoked session(s)")


def cmd_inspect_media(_: Session | None, args: argparse.Namespace) -> int:
    return report(args.paths)


def cmd_sync_videos(db: Session, args: argparse.Namespace) -> int:
    """Bring the catalogue in line with the folders under VIDEO_ROOT. Re-runnable."""
    result = sync_catalogue(
        db,
        get_settings().video_root,
        publish=args.publish,
        archive_missing=args.archive_missing,
        allow_mass_archive=args.allow_mass_archive,
    )
    record_sync_run(db, result, trigger="cli")
    print(result.report)
    if result.registered and not args.publish:
        print("Check them in the dashboard or with 'tree', then publish them.")
    return 1 if result.problems else 0


def cmd_relocate_content(db: Session, args: argparse.Namespace) -> int:
    lines = relocate_legacy_layout(db, get_settings().video_root, apply=args.apply)
    for line in lines:
        print(line)
    if not lines and not args.quiet:
        print("Nothing to move: every file is in its batch folder.")
    elif lines and not args.apply:
        print("Run again with --apply to move them.")
    return 0


# --------------------------------------------------------------------------- seed


def cmd_seed_demo(db: Session, args: argparse.Namespace) -> None:
    """Idempotently load demo batches, content and students from a JSON manifest."""
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    password: str | None = None

    for b in manifest.get("batches", []):
        name = _check_name(b["name"], "Batch name", 120)
        folder = _check_folder(b.get("folder"), name)
        batch = db.scalar(select(Batch).where(or_(Batch.folder == folder, Batch.name == name)))
        if batch is None:
            batch = Batch(name=name, folder=folder, description=b.get("description"))
            db.add(batch)
            db.flush()
            print(f"+ batch {batch.name}")
        for c in b.get("classes", []):
            class_name = _check_name(c["name"], "Class name", 100)
            class_folder = _check_folder(c.get("folder"), class_name)
            school_class = db.scalar(
                select(SchoolClass).where(
                    SchoolClass.batch_id == batch.id,
                    or_(SchoolClass.folder == class_folder, SchoolClass.name == class_name),
                )
            )
            if school_class is None:
                school_class = SchoolClass(
                    batch_id=batch.id, name=class_name, folder=class_folder, description=c.get("description")
                )
                db.add(school_class)
                db.flush()
                print(f"+ class {batch.name}/{school_class.name}")
            for s in c.get("subjects", []):
                subject_name = _check_name(s["name"], "Subject name", 150)
                subject_folder = _check_folder(s.get("folder"), subject_name)
                subject = db.scalar(
                    select(Subject).where(
                        Subject.class_id == school_class.id,
                        or_(Subject.folder == subject_folder, Subject.name == subject_name),
                    )
                )
                if subject is None:
                    subject = Subject(
                        class_id=school_class.id,
                        name=subject_name,
                        folder=subject_folder,
                        description=s.get("description"),
                        sort_order=s.get("sort_order", 0),
                    )
                    db.add(subject)
                    db.flush()
                    print(f"+ subject {school_class.name}/{subject.name}")
                for m in s.get("modules", []):
                    title = _check_name(m["title"], "Module title")
                    module_folder = _check_folder(m.get("folder"), title)
                    module = db.scalar(
                        select(Module).where(
                            Module.subject_id == subject.id, or_(Module.folder == module_folder, Module.title == title)
                        )
                    )
                    if module is None:
                        module = Module(
                            subject_id=subject.id,
                            title=title,
                            folder=module_folder,
                            description=m.get("description"),
                            sort_order=m.get("sort_order", 0),
                            is_published=m.get("published", False),
                        )
                        db.add(module)
                        db.flush()
                        print(f"+ module {subject.name}/{module.title}")
                    prefix = "/".join(p for p in (batch.folder, school_class.folder, subject.folder, module.folder) if p)
                    for item in m.get("contents", []):
                        _seed_content(db, module, item, prefix)

    for s in manifest.get("students", []):
        username = s["username"].strip().lower()
        if db.scalar(select(Student.id).where(Student.username == username)):
            continue
        if password is None:
            password = read_password(args, "Password for demo students: ")
        school_class = find_class(db, s["class"]) if s.get("class") else None
        db.add(
            Student(
                student_code=s["student_code"].strip().upper(),
                username=username,
                full_name=s["full_name"],
                password_hash=hash_password(password),
                class_id=school_class.id if school_class else None,
                is_active=s.get("active", True),
            )
        )
        db.flush()
        print(f"+ student {username}{'' if s.get('active', True) else ' (inactive)'}")
    print("Seed complete.")


def _seed_content(db: Session, module: Module, spec: dict, prefix: str) -> None:
    key = validate_storage_key(spec.get("storage_key") or f"{prefix}/{spec['file']}")
    if db.scalar(select(Content.id).where(Content.storage_key == key)):
        return
    try:
        _, info = inspect_content(key)
    except CliError as exc:
        print(f"! skipped {key}: {exc}")
        return
    wanted = spec.get("status", ContentStatus.DRAFT.value)
    status = wanted
    if wanted == ContentStatus.PUBLISHED.value and info.problems:
        status = ContentStatus.DRAFT.value
        print(f"! {key} left as draft: {'; '.join(info.problems)}")
    db.add(
        Content(
            module_id=module.id,
            title=spec["title"],
            description=spec.get("description"),
            storage_key=key,
            sort_order=spec.get("sort_order", 0),
            status=status,
            **info.metadata(),
        )
    )
    db.flush()
    print(f"+ {info.content_type.value} [{status}] {key}")


# --------------------------------------------------------------------------- parser


def _add_password_options(p: argparse.ArgumentParser) -> None:
    group = p.add_mutually_exclusive_group()
    group.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    group.add_argument("--password-env", metavar="VAR", help="read the password from an environment variable")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Campus LMS admin tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("tree", help="show batches, classes, subjects, modules and content")
    p.set_defaults(func=cmd_tree)

    p = sub.add_parser("create-batch")
    p.add_argument("name")
    p.add_argument("--folder", help="folder name under the content root (default: from the name)")
    p.add_argument("--description")
    p.set_defaults(func=cmd_create_batch)

    p = sub.add_parser("create-class")
    p.add_argument("--batch", help="batch name, folder or ID (optional when there is one batch)")
    p.add_argument("name")
    p.add_argument("--folder")
    p.add_argument("--description")
    p.set_defaults(func=cmd_create_class)

    p = sub.add_parser("create-subject")
    p.add_argument("--class", dest="class_ref", required=True, help='"Batch/Class", class name or ID')
    p.add_argument("name")
    p.add_argument("--folder")
    p.add_argument("--sort", type=int, default=0)
    p.set_defaults(func=cmd_create_subject)

    p = sub.add_parser("create-module", aliases=["create-chapter"])
    p.add_argument("--subject", required=True, help='"[Batch/]Class/Subject" or subject ID')
    p.add_argument("title")
    p.add_argument("--folder")
    p.add_argument("--description")
    p.add_argument("--sort", type=int, default=0)
    p.add_argument("--publish", action="store_true")
    p.set_defaults(func=cmd_create_module)

    for name, alias, value in (
        ("publish-module", "publish-chapter", True),
        ("unpublish-module", "unpublish-chapter", False),
    ):
        p = sub.add_parser(name, aliases=[alias])
        p.add_argument("module", help='"[Batch/]Class/Subject/Module" or module ID')
        p.set_defaults(func=cmd_set_module_published, publish_value=value)

    p = sub.add_parser("create-student")
    p.add_argument("--code", required=True, help="student code / ID")
    p.add_argument("--username", required=True)
    p.add_argument("--name", required=True, help="full name")
    p.add_argument("--class", dest="class_ref", help='"Batch/Class", class name or ID')
    _add_password_options(p)
    p.set_defaults(func=cmd_create_student)

    p = sub.add_parser("set-password", help="reset a student's password and sign them out")
    p.add_argument("student", help="username, student code or ID")
    _add_password_options(p)
    p.set_defaults(func=cmd_set_password)

    for name, value in (("activate-student", True), ("deactivate-student", False)):
        p = sub.add_parser(name)
        p.add_argument("student", help="username, student code or ID")
        p.set_defaults(func=cmd_set_student_active, active_value=value)

    p = sub.add_parser("assign-class")
    p.add_argument("student", help="username, student code or ID")
    p.add_argument("class_ref", metavar="class", help='"Batch/Class", class name or ID')
    p.set_defaults(func=cmd_assign_class)

    p = sub.add_parser("list-students")
    p.set_defaults(func=cmd_list_students)

    p = sub.add_parser("create-load-students", help="create students load001.. for deploy/scripts/load_test.py")
    p.add_argument("--count", type=int, required=True, help="how many (1-999)")
    p.add_argument("--prefix", default="load")
    p.add_argument("--class", dest="class_ref", required=True, help='"Batch/Class", class name or ID')
    _add_password_options(p)
    p.set_defaults(func=cmd_create_load_students)

    p = sub.add_parser("delete-load-students", help="delete the load-test students and their progress")
    p.add_argument("--prefix", default="load")
    p.set_defaults(func=cmd_delete_load_students)

    p = sub.add_parser("create-staff", help="create a dashboard account (teacher or administrator)")
    p.add_argument("--username", required=True)
    p.add_argument("--name", required=True, help="full name")
    p.add_argument("--role", choices=[r.value for r in StaffRole], default=StaffRole.STAFF.value)
    _add_password_options(p)
    p.set_defaults(func=cmd_create_staff)

    p = sub.add_parser("set-staff-password", help="reset a dashboard account's password")
    p.add_argument("staff", help="username or ID")
    _add_password_options(p)
    p.set_defaults(func=cmd_set_staff_password)

    for name, value in (("activate-staff", True), ("deactivate-staff", False)):
        p = sub.add_parser(name)
        p.add_argument("staff", help="username or ID")
        p.set_defaults(func=cmd_set_staff_active, active_value=value)

    p = sub.add_parser("list-staff")
    p.set_defaults(func=cmd_list_staff)

    p = sub.add_parser("add-content", aliases=["add-video"], help="register a file already in VIDEO_ROOT (as draft)")
    p.add_argument("--module", "--chapter", dest="module", required=True, help='"[Batch/]Class/Subject/Module" or ID')
    p.add_argument("--storage-key", required=True, help="path relative to VIDEO_ROOT")
    p.add_argument("--title", required=True)
    p.add_argument("--description")
    p.add_argument("--sort", type=int, default=0)
    p.set_defaults(func=cmd_add_content)

    for name, alias, status in (
        ("publish-content", "publish-video", ContentStatus.PUBLISHED),
        ("unpublish-content", "unpublish-video", ContentStatus.DRAFT),
        ("archive-content", "archive-video", ContentStatus.ARCHIVED),
    ):
        p = sub.add_parser(name, aliases=[alias])
        p.add_argument("content", help="content ID or storage key")
        if status is ContentStatus.PUBLISHED:
            p.add_argument("--force", action="store_true", help="publish even if the file has problems")
        p.set_defaults(func=cmd_set_content_status, status_value=status.value, force=False)

    p = sub.add_parser("check-media", help="verify every registered file exists and is readable")
    p.add_argument("--update", action="store_true", help="refresh size/duration/resolution metadata")
    p.set_defaults(func=cmd_check_media)

    p = sub.add_parser("scan-videos", aliases=["scan-content"], help="list content files that are not registered")
    p.set_defaults(func=cmd_scan_videos)

    p = sub.add_parser(
        "sync-videos",
        aliases=["sync-content"],
        help="update the catalogue from the folders <batch>/<class>/<subject>/<module>/<file>",
    )
    p.add_argument("--publish", action="store_true", help="publish new files that pass the check (default: draft)")
    p.add_argument("--archive-missing", action="store_true", help="archive items whose files are gone")
    p.add_argument(
        "--allow-mass-archive", action="store_true", help="archive even when more than half the files are missing"
    )
    p.set_defaults(func=cmd_sync_videos)

    p = sub.add_parser("relocate-content", help="move pre-batch folders into their batch folder (after upgrading)")
    p.add_argument("--apply", action="store_true", help="move the folders (default: only show what would move)")
    p.add_argument("--quiet", action="store_true", help="print nothing when there is nothing to do")
    p.set_defaults(func=cmd_relocate_content)

    p = sub.add_parser("inspect-media", help="show MP4 metadata for files (no database needed)")
    p.add_argument("paths", nargs="+")
    p.set_defaults(func=cmd_inspect_media, no_db=True)

    p = sub.add_parser("seed-demo", help="load demo content and students from a manifest")
    p.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    _add_password_options(p)
    p.set_defaults(func=cmd_seed_demo)

    p = sub.add_parser("purge-sessions", help="delete expired and revoked sessions")
    p.set_defaults(func=cmd_purge_sessions)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if getattr(args, "no_db", False):
            return args.func(None, args) or 0
        with session_scope() as db:
            return args.func(db, args) or 0
    except CliError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except IntegrityError as exc:
        print(f"Error: duplicate or invalid record ({exc.orig})", file=sys.stderr)
        return 2
    except DataError as exc:
        print(f"Error: a value is too long or out of range ({exc.orig})", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
