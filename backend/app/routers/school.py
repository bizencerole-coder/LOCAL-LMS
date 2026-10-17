"""The school's branding, notices and home-page banners for the student app."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..access import visible_modules, visible_subjects
from ..branding import audience_label, for_student, image_url, school_profile, student_batch_id, visible_notices
from ..db import get_db
from ..deps import get_student
from ..models import Banner, BannerLink, Module, Notice, Student, Subject, utcnow
from ..schemas import BannerLinkOut, BannerOut, NoticeOut, SchoolOut

router = APIRouter(prefix="/api/v1", tags=["school"])


@router.get("/school", response_model=SchoolOut)
def school(db: Session = Depends(get_db)) -> SchoolOut:
    profile = school_profile(db)
    return SchoolOut(
        name=profile.name,
        short_name=profile.short_name,
        tagline=profile.tagline,
        primary_color=profile.primary_color,
        logo_url=image_url(profile.logo_file),
        updated_at=profile.updated_at,
    )


@router.get("/notices", response_model=list[NoticeOut])
def notices(
    limit: int = Query(default=50, ge=1, le=200),
    student: Student = Depends(get_student),
    db: Session = Depends(get_db),
) -> list[NoticeOut]:
    """Published, unexpired notices for this student: important ones first, then newest."""
    batch_id = student_batch_id(db, student)
    rows = db.scalars(
        visible_notices(student, batch_id, utcnow())
        .order_by(Notice.is_important.desc(), Notice.published_at.desc(), Notice.id)
        .limit(limit)
    ).all()
    labels: dict[tuple, str] = {}
    out = []
    for notice in rows:
        key = (notice.batch_id, notice.class_id)
        if key not in labels:
            labels[key] = audience_label(db, *key)
        out.append(
            NoticeOut(
                id=notice.id,
                title=notice.title,
                body=notice.body,
                is_important=notice.is_important,
                published_at=notice.published_at,
                expires_at=notice.expires_at,
                audience=labels[key],
            )
        )
    return out


def _link(db: Session, student: Student, batch_id: uuid.UUID | None, banner: Banner) -> BannerLinkOut | None:
    """The banner's target, if this student may open it."""
    if banner.link_id is None:
        return None
    if banner.link_type == BannerLink.NOTICE:
        notice = db.scalar(visible_notices(student, batch_id, utcnow()).where(Notice.id == banner.link_id))
        return BannerLinkOut(type="notice", id=notice.id, title=notice.title) if notice else None
    if banner.link_type == BannerLink.SUBJECT:
        row = db.execute(visible_subjects(student, Subject.id, Subject.name).where(Subject.id == banner.link_id)).first()
        return BannerLinkOut(type="subject", id=row[0], title=row[1]) if row else None
    if banner.link_type == BannerLink.MODULE:
        row = db.execute(
            visible_modules(student, Module.id, Module.title, Module.subject_id).where(Module.id == banner.link_id)
        ).first()
        return BannerLinkOut(type="module", id=row[0], title=row[1], subject_id=row[2]) if row else None
    return None


@router.get("/banners", response_model=list[BannerOut])
def banners(student: Student = Depends(get_student), db: Session = Depends(get_db)) -> list[BannerOut]:
    """Active home-page banner slides for this student, in the order staff set."""
    now = utcnow()
    batch_id = student_batch_id(db, student)
    rows = db.scalars(
        select(Banner)
        .where(
            Banner.is_active.is_(True),
            or_(Banner.starts_at.is_(None), Banner.starts_at <= now),
            or_(Banner.ends_at.is_(None), Banner.ends_at > now),
            for_student(Banner, student, batch_id),
        )
        .order_by(Banner.sort_order, Banner.created_at, Banner.id)
    ).all()
    return [
        BannerOut(
            id=banner.id,
            title=banner.title,
            subtitle=banner.subtitle,
            image_url=image_url(banner.image_file),
            link=_link(db, student, batch_id, banner),
        )
        for banner in rows
    ]
