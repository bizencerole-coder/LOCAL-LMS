"""Dashboard pages for what the app shows around the lessons: notices, home-page
banners and the school's name, colour and logo."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from ..branding import (
    COLOR_RE,
    MAX_BANNER_BYTES,
    MAX_LOGO_BYTES,
    BrandingImageError,
    audience_label,
    image_url,
    remove_image_if_unused,
    save_image,
    school_profile,
)
from ..config import Settings, get_settings
from ..db import get_db
from ..models import (
    DEFAULT_SCHOOL_COLOR,
    Banner,
    BannerLink,
    Batch,
    Module,
    Notice,
    SchoolClass,
    SchoolProfile,
    StaffUser,
    Subject,
    as_utc,
    utcnow,
)
from . import ops
from .auth import Forbidden, current_staff, posted_form
from .web import FormError, NotFound, back, parse_local_date, redirect, render

router = APIRouter(prefix="/admin", include_in_schema=False)

ALL = "all"


def _get(db: Session, model, item_id: uuid.UUID, what: str):
    item = db.get(model, item_id)
    if item is None:
        raise NotFound(what)
    return item


def _flag(form, name: str) -> bool:
    return str(form.get(name, "")).lower() in {"1", "on", "true", "yes"}


def _ref(value: object) -> tuple[str, uuid.UUID | None]:
    """"kind:uuid" from a select -> (kind, id). Anything else -> ("", None)."""
    kind, _, raw = str(value or "").partition(":")
    try:
        return kind, uuid.UUID(raw)
    except ValueError:
        return kind, None


# ------------------------------------------------------------------ choices


def audience_options(db: Session) -> list[tuple[str, list[tuple[str, str]]]]:
    """Grouped <select> options: everyone, a batch, or one class."""
    batches = db.execute(select(Batch.id, Batch.name).order_by(Batch.sort_order, Batch.name)).all()
    classes = db.execute(
        select(SchoolClass.id, SchoolClass.name, Batch.name)
        .join(Batch, SchoolClass.batch_id == Batch.id)
        .order_by(Batch.sort_order, Batch.name, SchoolClass.sort_order, SchoolClass.name)
    ).all()
    return [
        ("", [(ALL, "All students")]),
        ("A batch", [(f"batch:{bid}", name) for bid, name in batches]),
        ("One class", [(f"class:{cid}", f"{batch} › {name}") for cid, name, batch in classes]),
    ]


def audience_value(item) -> str:
    if item.class_id:
        return f"class:{item.class_id}"
    if item.batch_id:
        return f"batch:{item.batch_id}"
    return ALL


def _audience(db: Session, form) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    value = str(form.get("audience") or ALL)
    if value == ALL:
        return None, None
    kind, item_id = _ref(value)
    if kind == "batch" and item_id and db.get(Batch, item_id):
        return item_id, None
    if kind == "class" and item_id and db.get(SchoolClass, item_id):
        return None, item_id
    raise FormError("Choose who should see it.")


def link_options(db: Session) -> list[tuple[str, list[tuple[str, str]]]]:
    """Grouped <select> options for what a banner opens."""
    notices = db.execute(
        select(Notice.id, Notice.title, Notice.published_at).order_by(Notice.created_at.desc()).limit(100)
    ).all()
    subjects = db.execute(
        select(Subject.id, Subject.name, SchoolClass.name, Batch.name)
        .join(SchoolClass, Subject.class_id == SchoolClass.id)
        .join(Batch, SchoolClass.batch_id == Batch.id)
        .order_by(Batch.sort_order, Batch.name, SchoolClass.sort_order, SchoolClass.name, Subject.sort_order, Subject.name)
    ).all()
    modules = db.execute(
        select(Module.id, Module.title, Subject.name, SchoolClass.name)
        .join(Subject, Module.subject_id == Subject.id)
        .join(SchoolClass, Subject.class_id == SchoolClass.id)
        .join(Batch, SchoolClass.batch_id == Batch.id)
        .order_by(
            Batch.sort_order, Batch.name, SchoolClass.sort_order, SchoolClass.name,
            Subject.sort_order, Subject.name, Module.sort_order, Module.title,
        )
    ).all()
    return [
        ("", [("", "Nothing (just the slide)")]),
        ("A notice", [(f"notice:{nid}", title + ("" if published else " (draft)")) for nid, title, published in notices]),
        ("A subject", [(f"subject:{sid}", f"{batch} › {klass} › {name}") for sid, name, klass, batch in subjects]),
        ("A module", [(f"module:{mid}", f"{klass} › {subject} › {title}") for mid, title, subject, klass in modules]),
    ]


def _link(db: Session, form) -> tuple[str | None, uuid.UUID | None]:
    value = str(form.get("link") or "")
    if not value:
        return None, None
    kind, item_id = _ref(value)
    model = {BannerLink.NOTICE: Notice, BannerLink.SUBJECT: Subject, BannerLink.MODULE: Module}.get(kind)
    if model is None or item_id is None or db.get(model, item_id) is None:
        raise FormError("The item the banner should open no longer exists. Choose another.")
    return kind, item_id


def link_label(db: Session, banner: Banner) -> str:
    if not banner.link_type or banner.link_id is None:
        return ""
    if banner.link_type == BannerLink.NOTICE:
        notice = db.get(Notice, banner.link_id)
        return f"Notice: {notice.title}" if notice else "(deleted notice)"
    if banner.link_type == BannerLink.SUBJECT:
        subject = db.get(Subject, banner.link_id)
        return f"Subject: {subject.name}" if subject else "(deleted subject)"
    module = db.get(Module, banner.link_id)
    return f"Module: {module.title}" if module else "(deleted module)"


async def _image(form, field: str) -> bytes | None:
    upload = form.get(field)
    if not isinstance(upload, UploadFile) or not upload.filename:
        return None
    return await upload.read()


# ------------------------------------------------------------------ notices


def _notice_status(notice: Notice) -> str:
    if notice.published_at is None:
        return "draft"
    if notice.expires_at is not None and as_utc(notice.expires_at) <= utcnow():
        return "expired"
    return "published"


@router.get("/notices")
def notices_page(request: Request, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    rows = db.scalars(select(Notice).order_by(Notice.created_at.desc())).all()
    return render(request, "notices.html", {
        "active": "notices",
        "rows": [(n, audience_label(db, n.batch_id, n.class_id), _notice_status(n)) for n in rows],
        "audiences": audience_options(db),
    })


def _apply_notice(db: Session, notice: Notice, form) -> None:
    notice.title = ops.clean_name(form.get("title"), "Title")
    notice.body = ops.clean_text(form.get("body"), max_length=5000)
    notice.batch_id, notice.class_id = _audience(db, form)
    notice.is_important = _flag(form, "is_important")
    notice.expires_at = parse_local_date(form.get("expires_on"), "Show until", end_of_day=True)


@router.post("/notices")
def create_notice(form=Depends(posted_form), staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    notice = Notice(created_by=staff.id)
    _apply_notice(db, notice, form)
    if _flag(form, "publish"):
        notice.published_at = utcnow()
    db.add(notice)
    db.commit()
    state = "published: students see it now" if notice.published_at else "saved as a draft"
    return redirect("/admin/notices", f"Notice {notice.title!r} {state}.")


@router.get("/notices/{notice_id}")
def notice_page(notice_id: uuid.UUID, request: Request, staff: StaffUser = Depends(current_staff),
                db: Session = Depends(get_db)):
    notice = _get(db, Notice, notice_id, "notice")
    return render(request, "notice.html", {
        "active": "notices",
        "notice": notice,
        "status": _notice_status(notice),
        "audience": audience_value(notice),
        "audiences": audience_options(db),
        "crumbs": [("Notices", "/admin/notices"), (notice.title, f"/admin/notices/{notice.id}")],
    })


@router.post("/notices/{notice_id}")
def update_notice(notice_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db)):
    notice = _get(db, Notice, notice_id, "notice")
    _apply_notice(db, notice, form)
    db.commit()
    return redirect(f"/admin/notices/{notice.id}", "Notice saved.")


@router.post("/notices/{notice_id}/publish")
def publish_notice(notice_id: uuid.UUID, request: Request, form=Depends(posted_form), db: Session = Depends(get_db)):
    notice = _get(db, Notice, notice_id, "notice")
    if _flag(form, "publish"):
        notice.published_at = utcnow()  # shown as new again
        message = f"{notice.title!r} published: students see it now."
    else:
        notice.published_at = None
        message = f"{notice.title!r} unpublished (draft)."
    db.commit()
    return redirect(back(request, "/admin/notices"), message)


@router.post("/notices/{notice_id}/delete")
def delete_notice(notice_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db)):
    notice = _get(db, Notice, notice_id, "notice")
    title = notice.title
    db.delete(notice)
    db.commit()
    return redirect("/admin/notices", f"Notice {title!r} deleted.")


# ------------------------------------------------------------------ banners


def _banner_rows(db: Session) -> list[Banner]:
    return list(db.scalars(select(Banner).order_by(Banner.sort_order, Banner.created_at, Banner.id)).all())


def _banner_state(banner: Banner) -> str:
    now = utcnow()
    if not banner.is_active:
        return "off"
    if banner.starts_at is not None and as_utc(banner.starts_at) > now:
        return "scheduled"
    if banner.ends_at is not None and as_utc(banner.ends_at) <= now:
        return "ended"
    return "showing"


@router.get("/banners")
def banners_page(request: Request, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    rows = _banner_rows(db)
    return render(request, "banners.html", {
        "active": "banners",
        "rows": [
            (b, image_url(b.image_file), link_label(db, b), audience_label(db, b.batch_id, b.class_id), _banner_state(b))
            for b in rows
        ],
        "audiences": audience_options(db),
        "links": link_options(db),
        "school": school_profile(db),
        "max_mb": MAX_BANNER_BYTES // (1024 * 1024),
    })


def _apply_banner(db: Session, banner: Banner, form) -> None:
    banner.title = ops.clean_name(form.get("title"), "Title", max_length=120)
    subtitle = ops.clean_text(form.get("subtitle"), max_length=240)
    banner.subtitle = subtitle
    banner.link_type, banner.link_id = _link(db, form)
    banner.batch_id, banner.class_id = _audience(db, form)
    banner.is_active = _flag(form, "is_active")
    banner.starts_at = parse_local_date(form.get("starts_on"), "Show from")
    banner.ends_at = parse_local_date(form.get("ends_on"), "Show until", end_of_day=True)
    if banner.starts_at and banner.ends_at and banner.ends_at <= banner.starts_at:
        raise FormError("“Show until” must be on or after “Show from”.")


async def _store_banner_image(form, settings: Settings) -> str | None:
    data = await _image(form, "image")
    if data is None:
        return None
    try:
        return save_image(settings.video_root, data, "banner", max_bytes=MAX_BANNER_BYTES)
    except BrandingImageError as exc:
        raise FormError(f"Banner picture: {exc}") from exc


@router.post("/banners")
async def create_banner(form=Depends(posted_form), db: Session = Depends(get_db),
                        settings: Settings = Depends(get_settings)):
    banner = Banner()
    _apply_banner(db, banner, form)
    banner.image_file = await _store_banner_image(form, settings)
    rows = _banner_rows(db)
    banner.sort_order = (max((b.sort_order for b in rows), default=0) or len(rows)) + 1
    db.add(banner)
    db.commit()
    return redirect("/admin/banners", f"Banner {banner.title!r} added.")


@router.get("/banners/{banner_id}")
def banner_page(banner_id: uuid.UUID, request: Request, staff: StaffUser = Depends(current_staff),
                db: Session = Depends(get_db)):
    banner = _get(db, Banner, banner_id, "banner")
    return render(request, "banner.html", {
        "active": "banners",
        "banner": banner,
        "image": image_url(banner.image_file),
        "state": _banner_state(banner),
        "audience": audience_value(banner),
        "audiences": audience_options(db),
        "link": f"{banner.link_type}:{banner.link_id}" if banner.link_type and banner.link_id else "",
        "link_text": link_label(db, banner),
        "links": link_options(db),
        "school": school_profile(db),
        "max_mb": MAX_BANNER_BYTES // (1024 * 1024),
        "crumbs": [("Banners", "/admin/banners"), (banner.title, f"/admin/banners/{banner.id}")],
    })


@router.post("/banners/{banner_id}")
async def update_banner(banner_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
                        settings: Settings = Depends(get_settings)):
    banner = _get(db, Banner, banner_id, "banner")
    old_image = banner.image_file
    _apply_banner(db, banner, form)
    new_image = await _store_banner_image(form, settings)
    if new_image:
        banner.image_file = new_image
    elif _flag(form, "remove_image"):
        banner.image_file = None
    db.commit()
    if old_image != banner.image_file:
        remove_image_if_unused(db, settings.video_root, old_image)
    return redirect(f"/admin/banners/{banner.id}", "Banner saved.")


@router.post("/banners/{banner_id}/move")
def move_banner(banner_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db)):
    banner = _get(db, Banner, banner_id, "banner")
    ops.reorder(db, _banner_rows(db), banner, str(form.get("direction")))
    db.commit()
    return redirect("/admin/banners")


@router.post("/banners/{banner_id}/delete")
def delete_banner(banner_id: uuid.UUID, form=Depends(posted_form), db: Session = Depends(get_db),
                  settings: Settings = Depends(get_settings)):
    banner = _get(db, Banner, banner_id, "banner")
    title, image = banner.title, banner.image_file
    db.delete(banner)
    db.commit()
    remove_image_if_unused(db, settings.video_root, image)
    return redirect("/admin/banners", f"Banner {title!r} deleted.")


# ------------------------------------------------------------------ school


def _require_admin(staff: StaffUser) -> None:
    if not staff.is_admin:
        raise Forbidden("Only administrators can change the school's name, colour and logo.")


@router.get("/school")
def school_page(request: Request, staff: StaffUser = Depends(current_staff), db: Session = Depends(get_db)):
    profile = school_profile(db)
    return render(request, "school.html", {
        "active": "school",
        "school": profile,
        "logo": image_url(profile.logo_file),
        "default_color": DEFAULT_SCHOOL_COLOR,
        "max_mb": MAX_LOGO_BYTES // (1024 * 1024),
        "can_edit": staff.is_admin,
    })


@router.post("/school")
async def save_school(form=Depends(posted_form), staff: StaffUser = Depends(current_staff),
                      db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _require_admin(staff)
    profile = db.get(SchoolProfile, 1)
    if profile is None:
        profile = SchoolProfile(id=1)
        db.add(profile)
    old_logo = profile.logo_file
    profile.name = ops.clean_name(form.get("name"), "School name")
    profile.short_name = ops.clean_text(form.get("short_name"), max_length=40)
    profile.tagline = ops.clean_text(form.get("tagline"), max_length=200)
    color = str(form.get("primary_color") or "").strip()
    if not COLOR_RE.match(color):
        raise FormError("Choose the school colour (for example #2E5AAC).")
    profile.primary_color = color.upper()
    data = await _image(form, "logo")
    if data is not None:
        try:
            profile.logo_file = save_image(settings.video_root, data, "logo", max_bytes=MAX_LOGO_BYTES)
        except BrandingImageError as exc:
            raise FormError(f"Logo: {exc}") from exc
    elif _flag(form, "remove_logo"):
        profile.logo_file = None
    db.commit()
    if old_logo != profile.logo_file:
        remove_image_if_unused(db, settings.video_root, old_logo)
    return redirect("/admin/school", "School details saved. Tablets show them the next time the app opens.")
