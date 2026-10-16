"""Prototype content administration (FR-08).

Run inside the API container, e.g.:

    docker compose exec api python -m app.cli tree
    docker compose exec api python -m app.cli add-video --chapter "Class 12/Computer Science/Python Basics" \\
        --storage-key class12/computer-science/lesson-04.mp4 --title "Lesson 4"

Admin actions are only available from the server shell; the student API has no
admin endpoints. Passwords are never accepted as command-line arguments.
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

from .config import get_settings
from .db import session_scope
from .media import ALLOWED_EXTENSIONS, InvalidStorageKey, resolve_media_path, validate_storage_key
from .models import (
    AuthSession,
    Chapter,
    SchoolClass,
    Student,
    Subject,
    Video,
    VideoStatus,
    utcnow,
)
from .mp4info import Mp4Error, inspect_mp4, report
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


def _check_name(value: str, what: str) -> str:
    value = value.strip()
    if not value:
        raise CliError(f"{what} must not be empty.")
    if "/" in value:
        raise CliError(f"{what} must not contain '/': {value!r}")
    return value


def find_class(db: Session, ref: str) -> SchoolClass:
    ref_id = _as_uuid(ref)
    found = (
        db.get(SchoolClass, ref_id)
        if ref_id
        else db.scalar(select(SchoolClass).where(SchoolClass.name == ref.strip()))
    )
    if found is None:
        raise CliError(f"Class not found: {ref}")
    return found


def find_subject(db: Session, ref: str) -> Subject:
    """By ID or "Class/Subject"."""
    ref_id = _as_uuid(ref)
    if ref_id:
        found = db.get(Subject, ref_id)
    else:
        parts = [p.strip() for p in ref.split("/")]
        if len(parts) != 2:
            raise CliError(f'Subject reference must be an ID or "Class/Subject": {ref}')
        school_class = find_class(db, parts[0])
        found = db.scalar(
            select(Subject).where(Subject.class_id == school_class.id, Subject.name == parts[1])
        )
    if found is None:
        raise CliError(f"Subject not found: {ref}")
    return found


def find_chapter(db: Session, ref: str) -> Chapter:
    """By ID or "Class/Subject/Chapter"."""
    ref_id = _as_uuid(ref)
    if ref_id:
        found = db.get(Chapter, ref_id)
    else:
        parts = [p.strip() for p in ref.split("/")]
        if len(parts) != 3:
            raise CliError(f'Chapter reference must be an ID or "Class/Subject/Chapter": {ref}')
        subject = find_subject(db, f"{parts[0]}/{parts[1]}")
        found = db.scalar(
            select(Chapter).where(Chapter.subject_id == subject.id, Chapter.title == parts[2])
        )
    if found is None:
        raise CliError(f"Chapter not found: {ref}")
    return found


def find_video(db: Session, ref: str) -> Video:
    """By ID or storage key."""
    ref_id = _as_uuid(ref)
    found = (
        db.get(Video, ref_id)
        if ref_id
        else db.scalar(select(Video).where(Video.storage_key == ref.strip()))
    )
    if found is None:
        raise CliError(f"Video not found: {ref}")
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


def inspect_video_file(storage_key: str) -> tuple[Path, dict, list[str]]:
    """Validate the key, check the file, and extract metadata.

    Returns (path, metadata for the Video row, problems). Raises CliError if the
    key is invalid or the file is missing/unreadable/not an MP4.
    """
    try:
        key = validate_storage_key(storage_key)
    except InvalidStorageKey as exc:
        raise CliError(str(exc)) from exc
    path = resolve_media_path(get_settings().video_root, key)
    if not path.is_file():
        raise CliError(f"File not found: {path}")
    if not os.access(path, os.R_OK):
        raise CliError(f"File is not readable: {path}")
    try:
        info = inspect_mp4(path)
    except (Mp4Error, OSError) as exc:
        raise CliError(f"Cannot read {path}: {exc}") from exc
    meta = {
        "file_size_bytes": info.size_bytes,
        "duration_seconds": round(info.duration_seconds) if info.duration_seconds else None,
        "resolution_width": info.width,
        "resolution_height": info.height,
        "mime_type": "video/mp4",
    }
    return path, meta, info.problems()


def _fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return "--:--"
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# --------------------------------------------------------------------------- commands


def cmd_create_class(db: Session, args: argparse.Namespace) -> None:
    item = SchoolClass(name=_check_name(args.name, "Class name"), description=args.description)
    db.add(item)
    db.flush()
    print(f"Created class {item.name} ({item.id})")


def cmd_create_subject(db: Session, args: argparse.Namespace) -> None:
    school_class = find_class(db, args.class_ref)
    item = Subject(
        class_id=school_class.id, name=_check_name(args.name, "Subject name"), sort_order=args.sort
    )
    db.add(item)
    db.flush()
    print(f"Created subject {school_class.name}/{item.name} ({item.id})")


def cmd_create_chapter(db: Session, args: argparse.Namespace) -> None:
    subject = find_subject(db, args.subject)
    item = Chapter(
        subject_id=subject.id,
        title=_check_name(args.title, "Chapter title"),
        description=args.description,
        sort_order=args.sort,
        is_published=args.publish,
    )
    db.add(item)
    db.flush()
    state = "published" if item.is_published else "unpublished"
    print(f"Created {state} chapter {item.title} ({item.id})")


def cmd_set_chapter_published(db: Session, args: argparse.Namespace) -> None:
    chapter = find_chapter(db, args.chapter)
    chapter.is_published = args.command == "publish-chapter"
    print(f"Chapter {chapter.title}: {'published' if chapter.is_published else 'unpublished'}")


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
    print(f"Password updated for {student.username}; {revoked} session(s) signed out.")


def cmd_set_student_active(db: Session, args: argparse.Namespace) -> None:
    student = find_student(db, args.student)
    student.is_active = args.command == "activate-student"
    revoked = 0 if student.is_active else revoke_sessions(db, student)
    state = "active" if student.is_active else f"inactive ({revoked} session(s) signed out)"
    print(f"Student {student.username}: {state}")


def cmd_assign_class(db: Session, args: argparse.Namespace) -> None:
    student = find_student(db, args.student)
    school_class = find_class(db, args.class_ref)
    student.class_id = school_class.id
    print(f"Student {student.username} assigned to {school_class.name}")


def cmd_list_students(db: Session, args: argparse.Namespace) -> None:
    rows = db.execute(
        select(Student, SchoolClass.name)
        .outerjoin(SchoolClass, Student.class_id == SchoolClass.id)
        .order_by(SchoolClass.name, Student.username)
    ).all()
    for student, class_name in rows:
        flag = "" if student.is_active else "  [inactive]"
        print(
            f"{student.username:<24} {student.student_code:<16} {class_name or '-':<16} "
            f"{student.id}  {student.full_name}{flag}"
        )
    print(f"{len(rows)} student(s)")


def _load_student_names(prefix: str, index: int) -> tuple[str, str]:
    return f"{prefix}{index:03d}", f"{prefix.upper()}-{index:03d}"


def cmd_create_load_students(db: Session, args: argparse.Namespace) -> None:
    """Students load001..loadNNN for deploy/scripts/load_test.py. Re-runnable."""
    if not re.fullmatch(r"[a-z][a-z0-9]{1,20}", args.prefix):
        raise CliError("--prefix must be 2-21 lower-case letters/digits (default: load)")
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
    print(f"Created {created} load-test student(s); {args.prefix}001..{args.prefix}{args.count:03d} exist in {school_class.name}")


def cmd_delete_load_students(db: Session, args: argparse.Namespace) -> None:
    """Delete load-test students (sessions and progress go with them)."""
    result = db.execute(
        delete(Student).where(
            Student.username.like(f"{args.prefix}___"),
            Student.student_code.like(f"{args.prefix.upper()}-___"),
        )
    )
    print(f"Deleted {result.rowcount or 0} load-test student(s) with prefix {args.prefix!r}")


def cmd_add_video(db: Session, args: argparse.Namespace) -> None:
    chapter = find_chapter(db, args.chapter)
    path, meta, problems = inspect_video_file(args.storage_key)
    key = validate_storage_key(args.storage_key)
    if db.scalar(select(Video.id).where(Video.storage_key == key)):
        raise CliError(f"A video is already registered for {key}")
    video = Video(
        chapter_id=chapter.id,
        title=args.title.strip(),
        description=args.description,
        storage_key=key,
        sort_order=args.sort,
        status=VideoStatus.DRAFT.value,
        **meta,
    )
    db.add(video)
    db.flush()
    print(f"Registered draft video {video.title} ({video.id})")
    print(f"  file: {path}  duration: {_fmt_duration(video.duration_seconds)}  "
          f"size: {meta['file_size_bytes'] / 1e6:.1f} MB  {meta['resolution_width']}x{meta['resolution_height']}")
    for problem in problems:
        print(f"  WARNING: {problem}")
    print("Check it plays, then run: python -m app.cli publish-video " + str(video.id))


def cmd_set_video_status(db: Session, args: argparse.Namespace) -> None:
    video = find_video(db, args.video)
    status = {
        "publish-video": VideoStatus.PUBLISHED,
        "unpublish-video": VideoStatus.DRAFT,
        "archive-video": VideoStatus.ARCHIVED,
    }[args.command]
    if status is VideoStatus.PUBLISHED and not args.force:
        _, meta, problems = inspect_video_file(video.storage_key)
        if problems:
            raise CliError(
                "Not publishing; the file has problems:\n  - " + "\n  - ".join(problems)
                + "\nFix the file, or pass --force to publish anyway."
            )
        for field_name, value in meta.items():
            setattr(video, field_name, value)
    video.status = status.value
    print(f"Video {video.title}: {status.value}")
    if status is not VideoStatus.PUBLISHED:
        ttl = get_settings().playback_url_ttl_seconds
        print(f"  Note: playback URLs already issued stay valid for up to {ttl // 60} minutes.")


def cmd_check_media(db: Session, args: argparse.Namespace) -> int:
    videos = db.scalars(select(Video).order_by(Video.storage_key)).all()
    failures = 0
    for video in videos:
        try:
            _, meta, problems = inspect_video_file(video.storage_key)
        except CliError as exc:
            failures += 1
            print(f"FAIL  {video.status:<9} {video.storage_key}: {exc}")
            continue
        if video.file_size_bytes and meta["file_size_bytes"] != video.file_size_bytes:
            problems.append(
                f"size changed since registration ({video.file_size_bytes} -> {meta['file_size_bytes']} bytes)"
            )
        if args.update:
            for field_name, value in meta.items():
                setattr(video, field_name, value)
        label = "WARN" if problems else "OK"
        print(f"{label:<5} {video.status:<9} {video.storage_key}  {_fmt_duration(meta['duration_seconds'])}")
        for problem in problems:
            print(f"      - {problem}")
    print(f"{len(videos)} video(s) checked, {failures} missing or unreadable")
    return 1 if failures else 0


def cmd_scan_videos(db: Session, args: argparse.Namespace) -> None:
    root = get_settings().video_root
    registered = set(db.scalars(select(Video.storage_key)))
    found = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        key = path.relative_to(root).as_posix()
        if key in registered:
            continue
        found += 1
        try:
            validate_storage_key(key)
            print(f"unregistered  {key}")
        except InvalidStorageKey:
            print(f"bad-name      {key}  (rename: letters, digits, '.', '-', '_' only)")
    print(f"{found} unregistered file(s) under {root}")


def cmd_tree(db: Session, args: argparse.Namespace) -> None:
    for school_class in db.scalars(select(SchoolClass).order_by(SchoolClass.name)):
        students = db.scalar(select(func.count(Student.id)).where(Student.class_id == school_class.id))
        flag = "" if school_class.is_active else " [inactive]"
        print(f"{school_class.name}{flag}  ({students} students)  id={school_class.id}")
        for subject in db.scalars(
            select(Subject).where(Subject.class_id == school_class.id).order_by(Subject.sort_order, Subject.name)
        ):
            flag = "" if subject.is_active else " [inactive]"
            print(f"  {subject.name}{flag}  id={subject.id}")
            for chapter in db.scalars(
                select(Chapter).where(Chapter.subject_id == subject.id).order_by(Chapter.sort_order, Chapter.title)
            ):
                flag = "" if chapter.is_published else " [unpublished]"
                print(f"    {chapter.title}{flag}  id={chapter.id}")
                for video in db.scalars(
                    select(Video).where(Video.chapter_id == chapter.id).order_by(Video.sort_order, Video.title)
                ):
                    print(
                        f"      [{video.status}] {video.title}  {_fmt_duration(video.duration_seconds)}  "
                        f"{video.storage_key}  id={video.id}"
                    )


def cmd_purge_sessions(db: Session, args: argparse.Namespace) -> None:
    cutoff = utcnow() - timedelta(days=1)
    result = db.execute(
        delete(AuthSession).where(
            or_(AuthSession.expires_at <= utcnow(), AuthSession.revoked_at <= cutoff)
        )
    )
    print(f"Deleted {result.rowcount or 0} expired/revoked session(s)")


def cmd_inspect_media(_: Session | None, args: argparse.Namespace) -> int:
    return report(args.paths)


def cmd_seed_demo(db: Session, args: argparse.Namespace) -> None:
    """Idempotently load demo classes, content and students from a JSON manifest."""
    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    password: str | None = None

    for c in manifest.get("classes", []):
        class_name = _check_name(c["name"], "Class name")
        school_class = db.scalar(select(SchoolClass).where(SchoolClass.name == class_name))
        if school_class is None:
            school_class = SchoolClass(name=class_name, description=c.get("description"))
            db.add(school_class)
            db.flush()
            print(f"+ class {school_class.name}")
        for s in c.get("subjects", []):
            subject_name = _check_name(s["name"], "Subject name")
            subject = db.scalar(
                select(Subject).where(Subject.class_id == school_class.id, Subject.name == subject_name)
            )
            if subject is None:
                subject = Subject(
                    class_id=school_class.id,
                    name=subject_name,
                    sort_order=s.get("sort_order", 0),
                )
                db.add(subject)
                db.flush()
                print(f"+ subject {school_class.name}/{subject.name}")
            for ch in s.get("chapters", []):
                chapter_title = _check_name(ch["title"], "Chapter title")
                chapter = db.scalar(
                    select(Chapter).where(Chapter.subject_id == subject.id, Chapter.title == chapter_title)
                )
                if chapter is None:
                    chapter = Chapter(
                        subject_id=subject.id,
                        title=chapter_title,
                        description=ch.get("description"),
                        sort_order=ch.get("sort_order", 0),
                        is_published=ch.get("published", False),
                    )
                    db.add(chapter)
                    db.flush()
                    print(f"+ chapter {subject.name}/{chapter.title}")
                for v in ch.get("videos", []):
                    _seed_video(db, chapter, v)

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


def _seed_video(db: Session, chapter: Chapter, spec: dict) -> None:
    key = validate_storage_key(spec["storage_key"])
    if db.scalar(select(Video.id).where(Video.storage_key == key)):
        return
    try:
        _, meta, problems = inspect_video_file(key)
    except CliError as exc:
        print(f"! skipped video {key}: {exc}")
        return
    wanted = spec.get("status", VideoStatus.DRAFT.value)
    status = wanted
    if wanted == VideoStatus.PUBLISHED.value and problems:
        status = VideoStatus.DRAFT.value
        print(f"! {key} left as draft: {'; '.join(problems)}")
    db.add(
        Video(
            chapter_id=chapter.id,
            title=spec["title"],
            description=spec.get("description"),
            storage_key=key,
            sort_order=spec.get("sort_order", 0),
            status=status,
            **meta,
        )
    )
    db.flush()
    print(f"+ video [{status}] {key}")


# --------------------------------------------------------------------------- parser


def _add_password_options(p: argparse.ArgumentParser) -> None:
    group = p.add_mutually_exclusive_group()
    group.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    group.add_argument("--password-env", metavar="VAR", help="read the password from an environment variable")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Campus LMS admin tool")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("tree", help="show classes, subjects, chapters and videos")
    p.set_defaults(func=cmd_tree)

    p = sub.add_parser("create-class")
    p.add_argument("name")
    p.add_argument("--description")
    p.set_defaults(func=cmd_create_class)

    p = sub.add_parser("create-subject")
    p.add_argument("--class", dest="class_ref", required=True, help="class name or ID")
    p.add_argument("name")
    p.add_argument("--sort", type=int, default=0)
    p.set_defaults(func=cmd_create_subject)

    p = sub.add_parser("create-chapter")
    p.add_argument("--subject", required=True, help='"Class/Subject" or subject ID')
    p.add_argument("title")
    p.add_argument("--description")
    p.add_argument("--sort", type=int, default=0)
    p.add_argument("--publish", action="store_true")
    p.set_defaults(func=cmd_create_chapter)

    for name in ("publish-chapter", "unpublish-chapter"):
        p = sub.add_parser(name)
        p.add_argument("chapter", help='"Class/Subject/Chapter" or chapter ID')
        p.set_defaults(func=cmd_set_chapter_published)

    p = sub.add_parser("create-student")
    p.add_argument("--code", required=True, help="student code / ID")
    p.add_argument("--username", required=True)
    p.add_argument("--name", required=True, help="full name")
    p.add_argument("--class", dest="class_ref", help="class name or ID")
    _add_password_options(p)
    p.set_defaults(func=cmd_create_student)

    p = sub.add_parser("set-password", help="reset a password and sign the student out")
    p.add_argument("student", help="username, student code or ID")
    _add_password_options(p)
    p.set_defaults(func=cmd_set_password)

    for name in ("activate-student", "deactivate-student"):
        p = sub.add_parser(name)
        p.add_argument("student", help="username, student code or ID")
        p.set_defaults(func=cmd_set_student_active)

    p = sub.add_parser("assign-class")
    p.add_argument("student", help="username, student code or ID")
    p.add_argument("class_ref", metavar="class", help="class name or ID")
    p.set_defaults(func=cmd_assign_class)

    p = sub.add_parser("list-students")
    p.set_defaults(func=cmd_list_students)

    p = sub.add_parser("create-load-students", help="create students load001.. for deploy/scripts/load_test.py")
    p.add_argument("--count", type=int, required=True, help="how many (1-999)")
    p.add_argument("--prefix", default="load")
    p.add_argument("--class", dest="class_ref", required=True, help="class name or ID")
    _add_password_options(p)
    p.set_defaults(func=cmd_create_load_students)

    p = sub.add_parser("delete-load-students", help="delete the load-test students and their progress")
    p.add_argument("--prefix", default="load")
    p.set_defaults(func=cmd_delete_load_students)

    p = sub.add_parser("add-video", help="register a file already in VIDEO_ROOT (as draft)")
    p.add_argument("--chapter", required=True, help='"Class/Subject/Chapter" or chapter ID')
    p.add_argument("--storage-key", required=True, help="path relative to VIDEO_ROOT")
    p.add_argument("--title", required=True)
    p.add_argument("--description")
    p.add_argument("--sort", type=int, default=0)
    p.set_defaults(func=cmd_add_video)

    for name in ("publish-video", "unpublish-video", "archive-video"):
        p = sub.add_parser(name)
        p.add_argument("video", help="video ID or storage key")
        if name == "publish-video":
            p.add_argument("--force", action="store_true", help="publish even if the file has problems")
        p.set_defaults(func=cmd_set_video_status, force=False)

    p = sub.add_parser("check-media", help="verify every registered file exists and is readable")
    p.add_argument("--update", action="store_true", help="refresh size/duration/resolution metadata")
    p.set_defaults(func=cmd_check_media)

    p = sub.add_parser("scan-videos", help="list MP4 files in VIDEO_ROOT that are not registered")
    p.set_defaults(func=cmd_scan_videos)

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
