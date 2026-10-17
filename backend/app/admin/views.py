"""Dashboard pages: content tree, students, staff, folder sync, account."""

from __future__ import annotations

import csv
import io
import secrets
import string
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..catalog_sync import record_sync_run, sync_catalogue
from ..config import Settings, get_settings
from ..db import get_db
from ..media import build_playback_url
from ..models import (
    AuthSession,
    Batch,
    Content,
    ContentProgress,
    ContentStatus,
    ContentType,
    Module,
    SchoolClass,
    StaffRole,
    StaffSession,
    StaffUser,
    Student,
    Subject,
    SyncRun,
    utcnow,
)
from ..security import MIN_PASSWORD_LENGTH, hash_password, verify_password
from ..storage import TRASH_DIR, UPLOADS_DIR, content_bytes, disk_usage, module_rel, path_for_key
from . import ops
from .auth import (
    Forbidden,
    authenticate,
    check_origin,
    current_staff,
    end_session,
    posted_form,
    require_admin,
    start_session,
)
from .web import FormError, NotFound, back, redirect, render, safe_admin_path, unwritable

router = APIRouter(prefix="/admin", include_in_schema=False)

PAGE_SIZE = 50


# --------------------------------------------------------------------------- helpers


def _get(db: Session, model, item_id: uuid.UUID, what: str):
    item = db.get(model, item_id)
    if item is None:
        raise NotFound(what)
    return item


def _flag(form, name: str) -> bool:
    return str(form.get(name, "")).lower() in {"1", "on", "true", "yes"}


def _uuid(value) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def _commit(db: Session, conflict_message: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise FormError(conflict_message) from exc


def _password_pair(form) -> str:
    password = str(form.get("password", ""))
    if len(password) < MIN_PASSWORD_LENGTH:
        raise FormError(f"The password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > 256:
        raise FormError("The password is too long.")
    if password != str(form.get("password_confirm", "")):
        raise FormError("The two passwords do not match.")
    return password


def _crumbs_for(db: Session, item) -> list[tuple[str, str]]:
    """Breadcrumb trail from "Content" down to ``item`` (inclusive)."""
    trail: list[tuple[str, str]] = []
    if isinstance(item, Content):
        trail.insert(0, (item.title, f"/admin/contents/{item.id}"))
        item = db.get(Module, item.module_id)
    if isinstance(item, Module):
        trail.insert(0, (item.title, f"/admin/modules/{item.id}"))
        item = db.get(Subject, item.subject_id)
    if isinstance(item, Subject):
        trail.insert(0, (item.name, f"/admin/subjects/{item.id}"))
        item = db.get(SchoolClass, item.class_id)
    if isinstance(item, SchoolClass):
        trail.insert(0, (item.name, f"/admin/classes/{item.id}"))
        item = db.get(Batch, item.batch_id)
    if isinstance(item, Batch):
        trail.insert(0, (item.name, f"/admin/batches/{item.id}"))
    trail.insert(0, ("Content", "/admin/batches"))
    return trail


def _share_path(settings: Settings, rel: str) -> str:
    base = (settings.content_share_path or "").strip()
    if not base:
        return f"videos/{rel}" if rel else "videos"
    sep = "\\" if "\\" in base else "/"
    return base.rstrip("\\/") + (sep + rel.replace("/", sep) if rel else "")


def _class_options(db: Session) -> list[tuple[uuid.UUID, str]]:
    rows = db.execute(
        select(SchoolClass.id, SchoolClass.name, Batch.name)
        .join(Batch, SchoolClass.batch_id == Batch.id)
        .order_by(Batch.sort_order, Batch.name, SchoolClass.sort_order, SchoolClass.name)
    ).all()
    return [(class_id, f"{batch_name} › {class_name}") for class_id, class_name, batch_name in rows]


def _content_counts(db: Session, group_column, *joins_where) -> dict:
    """{group id: (total, videos, notes, images)} for non-archived content."""
    stmt = select(
        group_column,
        func.count(Content.id),
        func.sum(case((Content.content_type == ContentType.VIDEO.value, 1), else_=0)),
        func.sum(case((Content.content_type == ContentType.PDF.value, 1), else_=0)),
        func.sum(case((Content.content_type == ContentType.IMAGE.value, 1), else_=0)),
    ).select_from(Content)
    for join in joins_where:
        stmt = join(stmt)
    stmt = stmt.where(Content.status != ContentStatus.ARCHIVED.value).group_by(group_column)
    return {row[0]: tuple(int(v or 0) for v in row[1:]) for row in db.execute(stmt).all()}


def _join_module(stmt):
    return stmt.join(Module, Content.module_id == Module.id)


def _join_subject(stmt):
    return stmt.join(Subject, Module.subject_id == Subject.id)


def _join_class(stmt):
    return stmt.join(SchoolClass, Subject.class_id == SchoolClass.id)


def _content_rows(db: Session, stmt) -> list[dict]:
    """Content rows with their place in the tree, for tables."""
    rows = db.execute(
        stmt.add_columns(Module.title, Subject.name, SchoolClass.name, Batch.name)
        .join(Module, Content.module_id == Module.id)
        .join(Subject, Module.subject_id == Subject.id)
        .join(SchoolClass, Subject.class_id == SchoolClass.id)
        .join(Batch, SchoolClass.batch_id == Batch.id)
    ).all()
    return [
        {"content": r[0], "where": f"{r[4]} › {r[3]} › {r[2]} › {r[1]}", "class_name": r[3], "module": r[1]}
        for r in rows
    ]


# --------------------------------------------------------------------------- sign-in


@router.get("/login")
def login_page(request: Request, next: str | None = None):
    return render(request, "login.html", {"next": safe_admin_path(next)})


@router.post("/login")
async def login(request: Request, db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    check_origin(request)
    form = await request.form()
    next_url = safe_admin_path(str(form.get("next", "")))
    username = str(form.get("username", ""))
    staff = authenticate(db, username, str(form.get("password", "")))
    if staff is None:
        return render(
            request,
            "login.html",
            {"next": next_url, "username": username[:100], "error": "Incorrect username or password."},
            status_code=401,
        )
    response = redirect(next_url)
    start_session(db, staff, settings, request, response)
    return response


@router.post("/logout")
def logout(request: Request, form=Depends(posted_form), db: Session = Depends(get_db)):
    response = redirect("/admin/login", "You have signed out.")
    end_session(db, request, response)
    return response


@router.get("")
def admin_root():
    return redirect("/admin/")


# --------------------------------------------------------------------------- dashboard


@router.get("/")
def dashboard(
    request: Request,
    staff: StaffUser = Depends(current_staff),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    by_type = dict(
        db.execute(
            select(Content.content_type, func.count(Content.id))
            .where(Content.status != ContentStatus.ARCHIVED.value)
            .group_by(Content.content_type)
        ).all()
    )
    stats = {
        "batches": db.scalar(select(func.count(Batch.id)).where(Batch.is_active.is_(True))) or 0,
        "classes": db.scalar(select(func.count(SchoolClass.id))) or 0,
        "students": db.scalar(select(func.count(Student.id)).where(Student.is_active.is_(True))) or 0,
        "videos": by_type.get(ContentType.VIDEO.value, 0),
        "notes": by_type.get(ContentType.PDF.value, 0),
        "images": by_type.get(ContentType.IMAGE.value, 0),
        "drafts": db.scalar(select(func.count(Content.id)).where(Content.status == ContentStatus.DRAFT.value)) or 0,
    }
    recent = _content_rows(db, select(Content).order_by(Content.created_at.desc()).limit(8))
    activity = db.execute(
        select(ContentProgress, Student.full_name, Student.id, Content.title, Content.content_type, Content.id)
        .join(Student, ContentProgress.student_id == Student.id)
        .join(Content, ContentProgress.content_id == Content.id)
        .order_by(ContentProgress.last_watched_at.desc())
        .limit(10)
    ).all()
    last_sync = db.scalar(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(1))
    root = settings.video_root
    return render(
        request,
        "dashboard.html",
        {
            "unwritable": unwritable(
                [root, root / UPLOADS_DIR, root / TRASH_DIR, *(root / f for f in db.scalars(select(Batch.folder)))]
            ),
            "stats": stats,
            "usage": disk_usage(settings.video_root),
            "content_bytes": content_bytes(db),
            "recent": recent,
            "activity": activity,
            "last_sync": last_sync,
            "active": "dashboard",
        },
    )


# --------------------------------------------------------------------------- batches


@router.get("/batches")
def batches_page(request: Request, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    batches = db.scalars(select(Batch).order_by(Batch.sort_order, Batch.name)).all()
    classes = db.scalars(select(SchoolClass).order_by(SchoolClass.sort_order, SchoolClass.name)).all()
    students = dict(
        db.execute(select(Student.class_id, func.count(Student.id)).group_by(Student.class_id)).all()
    )
    counts = _content_counts(db, SchoolClass.id, _join_module, _join_subject, _join_class)
    by_batch: dict = {}
    for school_class in classes:
        by_batch.setdefault(school_class.batch_id, []).append(school_class)
    return render(
        request,
        "batches.html",
        {
            "batches": batches,
            "classes_by_batch": by_batch,
            "students": students,
            "counts": counts,
            "active": "content",
            "crumbs": [("Content", "/admin/batches")],
        },
    )


@router.post("/batches")
def create_batch(form=Depends(posted_form), db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    batch = ops.create_batch(db, settings.video_root, form.get("name"), form.get("folder"), form.get("description"))
    _commit(db, "A batch with that name or folder already exists.")
    return redirect(f"/admin/batches/{batch.id}", f"Batch {batch.name} created (folder {batch.folder}).")


@router.get("/batches/{batch_id}")
def batch_page(
    batch_id: uuid.UUID,
    request: Request,
    staff: StaffUser = Depends(current_staff),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    batch = _get(db, Batch, batch_id, "batch")
    classes = db.scalars(
        select(SchoolClass).where(SchoolClass.batch_id == batch.id).order_by(SchoolClass.sort_order, SchoolClass.name)
    ).all()
    students = dict(
        db.execute(
            select(Student.class_id, func.count(Student.id))
            .where(Student.class_id.in_([c.id for c in classes]))
            .group_by(Student.class_id)
        ).all()
    ) if classes else {}
    subjects = dict(
        db.execute(
            select(Subject.class_id, func.count(Subject.id))
            .where(Subject.class_id.in_([c.id for c in classes]))
            .group_by(Subject.class_id)
        ).all()
    ) if classes else {}
    counts = _content_counts(db, SchoolClass.id, _join_module, _join_subject, _join_class)
    return render(
        request,
        "batch.html",
        {
            "batch": batch,
            "classes": classes,
            "students": students,
            "subjects": subjects,
            "counts": counts,
            "share": _share_path(settings, batch.folder),
            "active": "content",
            "crumbs": _crumbs_for(db, batch),
        },
    )


@router.post("/batches/{batch_id}")
def update_batch(
    batch_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    batch = _get(db, Batch, batch_id, "batch")
    name = ops.clean_name(form.get("name"), "Batch name", 120)
    if name != batch.name:
        ops.rename(db, settings.video_root, batch, name)
    batch.name = name
    batch.description = ops.clean_text(form.get("description"))
    batch.is_active = _flag(form, "is_active")
    batch.sort_order = _int(form.get("sort_order"), batch.sort_order)
    _commit(db, "Another batch already has that name.")
    return redirect(f"/admin/batches/{batch.id}", "Batch saved.")


@router.post("/batches/{batch_id}/delete")
def delete_batch(
    batch_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    batch = _get(db, Batch, batch_id, "batch")
    note = ops.delete_structure(db, settings.video_root, batch)
    db.commit()
    return redirect("/admin/batches", f"Batch {batch.name} deleted.{note}")


@router.post("/batches/{batch_id}/classes")
def create_class(
    batch_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    batch = _get(db, Batch, batch_id, "batch")
    item = ops.create_class(db, settings.video_root, batch, form.get("name"), form.get("folder"), form.get("description"))
    _commit(db, "A class with that name or folder already exists in this batch.")
    return redirect(f"/admin/classes/{item.id}", f"Class {item.name} created (folder {item.folder}).")


# --------------------------------------------------------------------------- classes


@router.get("/classes/{class_id}")
def class_page(
    class_id: uuid.UUID,
    request: Request,
    staff: StaffUser = Depends(current_staff),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    school_class = _get(db, SchoolClass, class_id, "class")
    batch = db.get(Batch, school_class.batch_id)
    subjects = db.scalars(
        select(Subject).where(Subject.class_id == school_class.id).order_by(Subject.sort_order, Subject.name)
    ).all()
    modules = dict(
        db.execute(
            select(Module.subject_id, func.count(Module.id))
            .where(Module.subject_id.in_([s.id for s in subjects]))
            .group_by(Module.subject_id)
        ).all()
    ) if subjects else {}
    counts = _content_counts(db, Subject.id, _join_module, _join_subject)
    student_count = db.scalar(select(func.count(Student.id)).where(Student.class_id == school_class.id)) or 0
    return render(
        request,
        "class.html",
        {
            "school_class": school_class,
            "batch": batch,
            "batches": db.scalars(select(Batch).order_by(Batch.name)).all(),
            "subjects": subjects,
            "modules": modules,
            "counts": counts,
            "student_count": student_count,
            "share": _share_path(settings, f"{batch.folder}/{school_class.folder}"),
            "active": "content",
            "crumbs": _crumbs_for(db, school_class),
        },
    )


@router.post("/classes/{class_id}")
def update_class(
    class_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    school_class = _get(db, SchoolClass, class_id, "class")
    name = ops.clean_name(form.get("name"), "Class name", 100)
    if name != school_class.name:
        ops.rename(db, settings.video_root, school_class, name)
    school_class.name = name
    school_class.description = ops.clean_text(form.get("description"))
    school_class.is_active = _flag(form, "is_active")
    school_class.sort_order = _int(form.get("sort_order"), school_class.sort_order)
    _commit(db, "Another class in this batch already has that name.")
    return redirect(f"/admin/classes/{school_class.id}", "Class saved.")


@router.post("/classes/{class_id}/delete")
def delete_class(
    class_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    school_class = _get(db, SchoolClass, class_id, "class")
    batch_id = school_class.batch_id
    note = ops.delete_structure(db, settings.video_root, school_class)
    db.commit()
    return redirect(f"/admin/batches/{batch_id}", f"Class {school_class.name} deleted.{note}")


@router.post("/classes/{class_id}/subjects")
def create_subject(
    class_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    school_class = _get(db, SchoolClass, class_id, "class")
    item = ops.create_subject(
        db, settings.video_root, school_class, form.get("name"), form.get("folder"), form.get("description")
    )
    _commit(db, "A subject with that name or folder already exists in this class.")
    return redirect(f"/admin/subjects/{item.id}", f"Subject {item.name} created (folder {item.folder}).")


# --------------------------------------------------------------------------- subjects


@router.get("/subjects/{subject_id}")
def subject_page(
    subject_id: uuid.UUID,
    request: Request,
    staff: StaffUser = Depends(current_staff),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    subject = _get(db, Subject, subject_id, "subject")
    school_class = db.get(SchoolClass, subject.class_id)
    batch = db.get(Batch, school_class.batch_id)
    modules = db.scalars(
        select(Module).where(Module.subject_id == subject.id).order_by(Module.sort_order, Module.title)
    ).all()
    counts = _content_counts(db, Module.id, _join_module)
    drafts = dict(
        db.execute(
            select(Content.module_id, func.count(Content.id))
            .where(Content.module_id.in_([m.id for m in modules]), Content.status == ContentStatus.DRAFT.value)
            .group_by(Content.module_id)
        ).all()
    ) if modules else {}
    return render(
        request,
        "subject.html",
        {
            "subject": subject,
            "school_class": school_class,
            "batch": batch,
            "modules": modules,
            "counts": counts,
            "drafts": drafts,
            "share": _share_path(settings, f"{batch.folder}/{school_class.folder}/{subject.folder}"),
            "active": "content",
            "crumbs": _crumbs_for(db, subject),
        },
    )


@router.post("/subjects/{subject_id}")
def update_subject(
    subject_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    subject = _get(db, Subject, subject_id, "subject")
    name = ops.clean_name(form.get("name"), "Subject name", 150)
    if name != subject.name:
        ops.rename(db, settings.video_root, subject, name)
    subject.name = name
    subject.description = ops.clean_text(form.get("description"))
    subject.is_active = _flag(form, "is_active")
    _commit(db, "Another subject in this class already has that name.")
    return redirect(f"/admin/subjects/{subject.id}", "Subject saved.")


@router.post("/subjects/{subject_id}/delete")
def delete_subject(
    subject_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    subject = _get(db, Subject, subject_id, "subject")
    class_id = subject.class_id
    note = ops.delete_structure(db, settings.video_root, subject)
    db.commit()
    return redirect(f"/admin/classes/{class_id}", f"Subject {subject.name} deleted.{note}")


@router.post("/subjects/{subject_id}/move")
def move_subject(subject_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db)):
    subject = _get(db, Subject, subject_id, "subject")
    siblings = db.scalars(
        select(Subject).where(Subject.class_id == subject.class_id).order_by(Subject.sort_order, Subject.name)
    ).all()
    ops.reorder(db, list(siblings), subject, str(form.get("direction")))
    db.commit()
    return redirect(f"/admin/classes/{subject.class_id}")


@router.post("/subjects/{subject_id}/modules")
def create_module(
    subject_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    subject = _get(db, Subject, subject_id, "subject")
    item = ops.create_module(
        db, settings.video_root, subject, form.get("title"), form.get("folder"), form.get("description"),
        _flag(form, "is_published"),
    )
    _commit(db, "A module with that title or folder already exists in this subject.")
    return redirect(f"/admin/modules/{item.id}", f"Module {item.title} created (folder {item.folder}).")


# --------------------------------------------------------------------------- modules


@router.get("/modules/{module_id}")
def module_page(
    module_id: uuid.UUID,
    request: Request,
    staff: StaffUser = Depends(current_staff),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    module = _get(db, Module, module_id, "module")
    subject = db.get(Subject, module.subject_id)
    school_class = db.get(SchoolClass, subject.class_id)
    batch = db.get(Batch, school_class.batch_id)
    items = db.scalars(
        select(Content).where(Content.module_id == module.id).order_by(Content.sort_order, Content.title)
    ).all()
    missing = {c.id for c in items if not path_for_key(settings.video_root, c.storage_key).is_file()}
    rel = module_rel(batch, school_class, subject, module)
    folder = path_for_key(settings.video_root, rel)
    while not folder.exists() and folder != settings.video_root:
        folder = folder.parent  # uploads create the missing folders below this one
    return render(
        request,
        "module.html",
        {
            "module": module,
            "subject": subject,
            "school_class": school_class,
            "batch": batch,
            "items": items,
            "missing": missing,
            "unwritable": unwritable([folder, settings.video_root / UPLOADS_DIR]),
            "share": _share_path(settings, rel),
            "max_upload": settings.upload_max_bytes,
            "active": "content",
            "crumbs": _crumbs_for(db, module),
        },
    )


@router.post("/modules/{module_id}")
def update_module(
    module_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    module = _get(db, Module, module_id, "module")
    title = ops.clean_name(form.get("title"), "Module title")
    if title != module.title:
        ops.rename(db, settings.video_root, module, title)
    module.title = title
    module.description = ops.clean_text(form.get("description"))
    module.is_published = _flag(form, "is_published")
    _commit(db, "Another module in this subject already has that title.")
    return redirect(f"/admin/modules/{module.id}", "Module saved.")


@router.post("/modules/{module_id}/delete")
def delete_module(
    module_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    module = _get(db, Module, module_id, "module")
    subject_id = module.subject_id
    note = ops.delete_structure(db, settings.video_root, module)
    db.commit()
    return redirect(f"/admin/subjects/{subject_id}", f"Module {module.title} deleted.{note}")


@router.post("/modules/{module_id}/move")
def move_module(module_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db)):
    module = _get(db, Module, module_id, "module")
    siblings = db.scalars(
        select(Module).where(Module.subject_id == module.subject_id).order_by(Module.sort_order, Module.title)
    ).all()
    ops.reorder(db, list(siblings), module, str(form.get("direction")))
    db.commit()
    return redirect(f"/admin/subjects/{module.subject_id}")


# --------------------------------------------------------------------------- content


@router.get("/contents/{content_id}")
def content_page(
    content_id: uuid.UUID,
    request: Request,
    staff: StaffUser = Depends(current_staff),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    content = _get(db, Content, content_id, "item")
    module = db.get(Module, content.module_id)
    subject = db.get(Subject, module.subject_id)
    school_class = db.get(SchoolClass, subject.class_id)
    exists, problems = ops.file_problems(settings.video_root, content)
    preview = None
    if exists:
        expires = int(utcnow().timestamp()) + 3600
        preview = build_playback_url(
            base_url="",
            prefix=settings.media_url_prefix,
            storage_key=content.storage_key,
            sid=f"staff-{staff.id}",
            expires=expires,
            secret=settings.media_signing_secret,
        )
    targets = db.execute(
        select(Module.id, Module.title, Subject.name)
        .join(Subject, Module.subject_id == Subject.id)
        .where(Subject.class_id == school_class.id)
        .order_by(Subject.sort_order, Subject.name, Module.sort_order, Module.title)
    ).all()
    viewers = db.scalar(select(func.count(ContentProgress.id)).where(ContentProgress.content_id == content.id)) or 0
    completed = db.scalar(
        select(func.count(ContentProgress.id)).where(
            ContentProgress.content_id == content.id, ContentProgress.is_completed.is_(True)
        )
    ) or 0
    return render(
        request,
        "content.html",
        {
            "content": content,
            "module": module,
            "subject": subject,
            "school_class": school_class,
            "exists": exists,
            "problems": problems,
            "preview": preview,
            "targets": targets,
            "viewers": viewers,
            "completed": completed,
            "share": _share_path(settings, content.storage_key),
            "active": "content",
            "crumbs": _crumbs_for(db, content),
        },
    )


@router.post("/contents/{content_id}")
def update_content(
    content_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    content = _get(db, Content, content_id, "item")
    ops.update_content_text(settings.video_root, content, form.get("title"), form.get("description"))
    target_id = _uuid(form.get("module_id"))
    moved = False
    if target_id and target_id != content.module_id:
        target = _get(db, Module, target_id, "module")
        current = db.get(Module, content.module_id)
        if db.get(Subject, target.subject_id).class_id != db.get(Subject, current.subject_id).class_id:
            raise FormError("Items can only be moved to a module of the same class.")
        ops.move_content(db, settings.video_root, content, target)
        moved = True
    db.commit()
    return redirect(f"/admin/contents/{content.id}", "Moved and saved." if moved else "Saved.")


@router.post("/contents/{content_id}/status")
def set_content_status(
    content_id: uuid.UUID, request: Request, form=Depends(posted_form), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    content = _get(db, Content, content_id, "item")
    try:
        status = ContentStatus(str(form.get("status")))
    except ValueError as exc:
        raise FormError("Unknown status.") from exc
    ops.set_status(db, settings.video_root, content, status, force=_flag(form, "force"))
    db.commit()
    labels = {"published": "published: students can see it now", "draft": "unpublished (draft)",
              "archived": "archived: hidden, file kept"}
    return redirect(back(request, f"/admin/modules/{content.module_id}"), f"{content.title} {labels[status.value]}.")


@router.post("/contents/{content_id}/move")
def move_content_order(content_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db)):
    content = _get(db, Content, content_id, "item")
    siblings = db.scalars(
        select(Content).where(Content.module_id == content.module_id).order_by(Content.sort_order, Content.title)
    ).all()
    ops.reorder(db, list(siblings), content, str(form.get("direction")))
    db.commit()
    return redirect(f"/admin/modules/{content.module_id}")


@router.post("/contents/{content_id}/delete")
def delete_content(
    content_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    content = _get(db, Content, content_id, "item")
    module_id = content.module_id
    ops.delete_content(db, settings.video_root, content)
    db.commit()
    return redirect(
        f"/admin/modules/{module_id}",
        f"{content.title} deleted. Its file is kept in the .trash folder for 30 days.",
    )


# --------------------------------------------------------------------------- students


@router.get("/students")
def students_page(
    request: Request,
    q: str = Query(default="", max_length=100),
    class_id: str = "",
    status: str = "active",
    page: int = Query(default=1, ge=1, le=10000),
    staff: StaffUser = Depends(current_staff),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Student, SchoolClass.name, Batch.name)
        .outerjoin(SchoolClass, Student.class_id == SchoolClass.id)
        .outerjoin(Batch, SchoolClass.batch_id == Batch.id)
    )
    q_clean = q.strip().replace("\x00", "")
    if q_clean:
        like = f"%{q_clean.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Student.full_name).like(like),
                Student.username.like(like),
                func.lower(Student.student_code).like(like),
            )
        )
    class_uuid = _uuid(class_id)
    if class_id == "none":
        stmt = stmt.where(Student.class_id.is_(None))
    elif class_uuid:
        stmt = stmt.where(Student.class_id == class_uuid)
    if status == "active":
        stmt = stmt.where(Student.is_active.is_(True))
    elif status == "inactive":
        stmt = stmt.where(Student.is_active.is_(False))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(Batch.name, SchoolClass.name, Student.full_name).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    ).all()
    ids = [r[0].id for r in rows]
    last_seen = dict(
        db.execute(
            select(ContentProgress.student_id, func.max(ContentProgress.last_watched_at))
            .where(ContentProgress.student_id.in_(ids))
            .group_by(ContentProgress.student_id)
        ).all()
    ) if ids else {}
    return render(
        request,
        "students.html",
        {
            "rows": rows,
            "last_seen": last_seen,
            "total": total,
            "page": page,
            "pages": max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE),
            "q": q_clean,
            "class_id": class_id,
            "status": status,
            "class_options": _class_options(db),
            "active": "students",
        },
    )


@router.post("/students")
def create_student(form=Depends(posted_form), db: Session = Depends(get_db)):
    code = ops.clean_name(form.get("student_code"), "Student ID", 50).upper()
    username = ops.clean_name(form.get("username"), "Username", 100).lower()
    full_name = ops.clean_name(form.get("full_name"), "Full name")
    class_id = _uuid(form.get("class_id"))
    if class_id and db.get(SchoolClass, class_id) is None:
        raise FormError("Choose a class from the list.")
    password = _password_pair(form)
    if db.scalar(select(Student.id).where(or_(Student.username == username, Student.student_code == code))):
        raise FormError("A student with that username or student ID already exists.")
    student = Student(
        student_code=code, username=username, full_name=full_name, password_hash=hash_password(password),
        class_id=class_id, is_active=True,
    )
    db.add(student)
    _commit(db, "A student with that username or student ID already exists.")
    return redirect(f"/admin/students/{student.id}", f"Student {full_name} created. They can sign in as {username}.")


def _generate_password() -> str:
    alphabet = "".join(c for c in string.ascii_letters + string.digits if c not in "0O1lI")
    return "".join(secrets.choice(alphabet) for _ in range(10))


@router.get("/students/import")
def import_page(request: Request, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    return render(request, "students_import.html", {"class_options": _class_options(db), "active": "students"})


@router.post("/students/import")
async def import_students(request: Request, form=Depends(posted_form), db: Session = Depends(get_db)):
    text = str(form.get("csv_text") or "")
    upload = form.get("csv_file")
    if upload is not None and hasattr(upload, "read"):
        data = await upload.read()
        if data:
            text = data.decode("utf-8-sig", errors="replace")
    default_class = _uuid(form.get("class_id"))
    from starlette.concurrency import run_in_threadpool

    results = await run_in_threadpool(_import_rows, db, text, default_class)
    return render(
        request,
        "students_import.html",
        {"class_options": _class_options(db), "results": results, "active": "students"},
    )


def _import_rows(db: Session, text: str, default_class: uuid.UUID | None) -> dict:
    from ..cli import CliError, find_class

    reader = csv.DictReader(io.StringIO(text.strip()))
    fields = {f.strip().lower() for f in (reader.fieldnames or [])}
    needed = {"student_code", "username", "full_name"}
    if not needed <= fields:
        return {"error": "The first line must be a header with: student_code, username, full_name "
                         "(and optionally class, password).", "created": [], "skipped": []}
    created, skipped = [], []
    seen: set[str] = set()
    for number, raw in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
        code, username, name = row.get("student_code", "").upper(), row.get("username", "").lower(), row.get("full_name", "")
        if not (code and username and name):
            skipped.append((number, username or code or "?", "student_code, username and full_name are required"))
            continue
        if len(code) > 50 or len(username) > 100 or len(name) > 200 or "\x00" in code + username + name:
            skipped.append((number, username, "a value is too long"))
            continue
        if username in seen or code in seen or db.scalar(
            select(Student.id).where(or_(Student.username == username, Student.student_code == code))
        ):
            skipped.append((number, username, "username or student ID already exists"))
            continue
        class_id = default_class
        if row.get("class"):
            try:
                class_id = find_class(db, row["class"]).id
            except CliError as exc:
                skipped.append((number, username, str(exc)))
                continue
        password = row.get("password") or ""
        generated = not password
        if generated:
            password = _generate_password()
        elif len(password) < MIN_PASSWORD_LENGTH:
            skipped.append((number, username, f"password shorter than {MIN_PASSWORD_LENGTH} characters"))
            continue
        db.add(Student(student_code=code, username=username, full_name=name, password_hash=hash_password(password),
                       class_id=class_id, is_active=True))
        seen.update({username, code})
        created.append({"code": code, "username": username, "name": name,
                        "password": password if generated else "(as given)"})
    db.commit()
    lines = ["student_code,username,full_name,password"] + [
        f"{c['code']},{c['username']},\"{c['name']}\",{c['password']}" for c in created
    ]
    return {"created": created, "skipped": skipped, "csv": "\n".join(lines), "error": None}


@router.get("/students/{student_id}")
def student_page(
    student_id: uuid.UUID,
    request: Request,
    staff: StaffUser = Depends(current_staff),
    db: Session = Depends(get_db),
):
    student = _get(db, Student, student_id, "student")
    progress = db.execute(
        select(ContentProgress, Content.title, Content.content_type, Content.duration_seconds, Content.id)
        .join(Content, ContentProgress.content_id == Content.id)
        .where(ContentProgress.student_id == student.id)
        .order_by(ContentProgress.last_watched_at.desc())
        .limit(30)
    ).all()
    sessions = db.scalar(
        select(func.count(AuthSession.id)).where(
            AuthSession.student_id == student.id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > utcnow()
        )
    ) or 0
    return render(
        request,
        "student.html",
        {
            "student": student,
            "progress": progress,
            "sessions": sessions,
            "class_options": _class_options(db),
            "active": "students",
        },
    )


def _revoke_student_sessions(db: Session, student: Student) -> int:
    result = db.execute(
        update(AuthSession)
        .where(AuthSession.student_id == student.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    return result.rowcount or 0


@router.post("/students/{student_id}")
def update_student(student_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db)):
    student = _get(db, Student, student_id, "student")
    student.full_name = ops.clean_name(form.get("full_name"), "Full name")
    student.username = ops.clean_name(form.get("username"), "Username", 100).lower()
    student.student_code = ops.clean_name(form.get("student_code"), "Student ID", 50).upper()
    class_id = _uuid(form.get("class_id"))
    if class_id and db.get(SchoolClass, class_id) is None:
        raise FormError("Choose a class from the list.")
    student.class_id = class_id
    was_active = student.is_active
    student.is_active = _flag(form, "is_active")
    note = ""
    if was_active and not student.is_active:
        note = f" {_revoke_student_sessions(db, student)} session(s) signed out."
    _commit(db, "Another student already has that username or student ID.")
    return redirect(f"/admin/students/{student.id}", "Student saved." + note)


@router.post("/students/{student_id}/password")
def reset_student_password(student_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db)):
    student = _get(db, Student, student_id, "student")
    student.password_hash = hash_password(_password_pair(form))
    revoked = _revoke_student_sessions(db, student)
    db.commit()
    return redirect(f"/admin/students/{student.id}", f"Password changed; {revoked} session(s) signed out.")


@router.post("/students/{student_id}/signout")
def sign_out_student(student_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db)):
    student = _get(db, Student, student_id, "student")
    revoked = _revoke_student_sessions(db, student)
    db.commit()
    return redirect(f"/admin/students/{student.id}", f"{revoked} session(s) signed out.")


@router.post("/students/{student_id}/delete")
def delete_student(
    student_id: uuid.UUID, form=Depends(posted_form), admin: StaffUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    student = _get(db, Student, student_id, "student")
    db.delete(student)
    db.commit()
    return redirect("/admin/students", f"Student {student.full_name} and their progress were deleted.")


# --------------------------------------------------------------------------- staff


@router.get("/staff")
def staff_page(request: Request, admin: StaffUser = Depends(require_admin), db: Session = Depends(get_db)):
    members = db.scalars(select(StaffUser).order_by(StaffUser.role, StaffUser.full_name)).all()
    return render(request, "staff.html", {"members": members, "roles": [r.value for r in StaffRole], "active": "staff"})


@router.post("/staff")
def create_staff(form=Depends(posted_form), admin: StaffUser = Depends(require_admin), db: Session = Depends(get_db)):
    username = ops.clean_name(form.get("username"), "Username", 100).lower()
    if not all(c.isalnum() or c in "._-" for c in username):
        raise FormError("Usernames may use letters, digits, '.', '-' and '_' only.")
    role = str(form.get("role"))
    if role not in {r.value for r in StaffRole}:
        raise FormError("Choose a role.")
    member = StaffUser(
        username=username,
        full_name=ops.clean_name(form.get("full_name"), "Full name"),
        password_hash=hash_password(_password_pair(form)),
        role=role,
        is_active=True,
    )
    db.add(member)
    _commit(db, f"A staff account called {username!r} already exists.")
    return redirect("/admin/staff", f"Account {username} created.")


@router.get("/staff/{member_id}")
def staff_member_page(
    member_id: uuid.UUID, request: Request, admin: StaffUser = Depends(require_admin), db: Session = Depends(get_db)
):
    member = _get(db, StaffUser, member_id, "staff account")
    return render(
        request, "staff_member.html", {"member": member, "roles": [r.value for r in StaffRole], "active": "staff"}
    )


def _active_admins(db: Session) -> int:
    return db.scalar(
        select(func.count(StaffUser.id)).where(StaffUser.role == StaffRole.ADMIN.value, StaffUser.is_active.is_(True))
    ) or 0


@router.post("/staff/{member_id}")
def update_staff_member(
    member_id: uuid.UUID, form=Depends(posted_form), admin: StaffUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    member = _get(db, StaffUser, member_id, "staff account")
    role = str(form.get("role"))
    if role not in {r.value for r in StaffRole}:
        raise FormError("Choose a role.")
    active = _flag(form, "is_active")
    losing_admin = member.is_admin and member.is_active and (role != StaffRole.ADMIN.value or not active)
    if losing_admin and _active_admins(db) <= 1:
        raise FormError("Keep at least one active administrator.")
    member.full_name = ops.clean_name(form.get("full_name"), "Full name")
    member.role = role
    if member.is_active and not active:
        db.execute(
            update(StaffSession)
            .where(StaffSession.staff_id == member.id, StaffSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
    member.is_active = active
    db.commit()
    return redirect(f"/admin/staff/{member.id}", "Account saved.")


@router.post("/staff/{member_id}/password")
def reset_staff_password(
    member_id: uuid.UUID, request: Request, form=Depends(posted_form), admin: StaffUser = Depends(require_admin),
    db: Session = Depends(get_db),
):
    member = _get(db, StaffUser, member_id, "staff account")
    member.password_hash = hash_password(_password_pair(form))
    if member.id != admin.id:
        db.execute(
            update(StaffSession)
            .where(StaffSession.staff_id == member.id, StaffSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
        )
    db.commit()
    return redirect(f"/admin/staff/{member.id}", "Password changed.")


# --------------------------------------------------------------------------- account


@router.get("/account")
def account_page(request: Request, staff: StaffUser = Depends(current_staff)):
    return render(request, "account.html", {"active": "account"})


@router.post("/account/password")
def change_own_password(
    request: Request, form=Depends(posted_form), staff: StaffUser = Depends(current_staff),
    db: Session = Depends(get_db),
):
    if not verify_password(staff.password_hash, str(form.get("current_password", ""))):
        raise FormError("Your current password is not correct.")
    member = db.get(StaffUser, staff.id)
    member.password_hash = hash_password(_password_pair(form))
    db.execute(
        update(StaffSession)
        .where(
            StaffSession.staff_id == member.id,
            StaffSession.revoked_at.is_(None),
            StaffSession.id != request.state.staff_session_id,
        )
        .values(revoked_at=utcnow())
    )
    db.commit()
    return redirect("/admin/account", "Password changed. Other dashboard sessions were signed out.")


# --------------------------------------------------------------------------- folder sync


@router.get("/sync")
def sync_page(
    request: Request,
    run: uuid.UUID | None = None,
    staff: StaffUser = Depends(current_staff),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    runs = db.scalars(select(SyncRun).order_by(SyncRun.started_at.desc()).limit(30)).all()
    selected = db.get(SyncRun, run) if run else (runs[0] if runs else None)
    return render(
        request,
        "sync.html",
        {"runs": runs, "selected": selected, "share": _share_path(settings, ""), "active": "sync"},
    )


@router.post("/sync")
def run_sync(
    form=Depends(posted_form),
    staff: StaffUser = Depends(current_staff),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    result = sync_catalogue(
        db,
        settings.video_root,
        publish=_flag(form, "publish"),
        archive_missing=_flag(form, "archive_missing"),
    )
    run = record_sync_run(db, result, trigger="dashboard", staff_id=staff.id)
    db.commit()
    level = "warning" if result.problems else "success"
    return redirect(f"/admin/sync?run={run.id}", result.summary, level)


# Keep Forbidden importable for the exception handlers (main.py).
__all__ = ["router", "Forbidden"]
