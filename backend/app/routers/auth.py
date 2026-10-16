"""Local sign-in and sign-out (FR-01). No external identity provider."""

from __future__ import annotations

import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import Auth, get_auth
from ..errors import ApiError
from ..logging_config import log_event
from ..models import AuthSession, SchoolClass, Student, utcnow
from ..schemas import ClassInfo, LoginRequest, LoginResponse, MeResponse, StudentSummary
from ..security import (
    burn_dummy_verification,
    hash_password,
    hash_session_token,
    new_session_token,
    password_needs_rehash,
    verify_password,
)

router = APIRouter(prefix="/api/v1", tags=["auth"])
logger = logging.getLogger("app.auth")

def _invalid_credentials() -> ApiError:
    return ApiError(401, "invalid_credentials", "Incorrect username or password.")


def _find_student(db: Session, identifier: str) -> Student | None:
    identifier = identifier.strip()
    if "\x00" in identifier:
        # PostgreSQL rejects NUL in text parameters; no stored name can contain one.
        return None
    by_username = db.scalar(select(Student).where(Student.username == identifier.lower()))
    if by_username is not None:
        return by_username
    return db.scalar(select(Student).where(Student.student_code == identifier.upper()))


@router.post("/auth/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> LoginResponse:
    student = _find_student(db, body.username)
    if student is None:
        burn_dummy_verification(body.password)
        log_event(logger, "login_failed", logging.WARNING, reason="unknown_user")
        raise _invalid_credentials()
    if not verify_password(student.password_hash, body.password):
        log_event(logger, "login_failed", logging.WARNING, reason="bad_password", student_id=student.id)
        raise _invalid_credentials()
    if not student.is_active:
        log_event(logger, "login_failed", logging.WARNING, reason="inactive", student_id=student.id)
        raise ApiError(
            403,
            "account_inactive",
            "This account is not active. Please contact your teacher or administrator.",
        )

    if password_needs_rehash(student.password_hash):
        student.password_hash = hash_password(body.password)

    now = utcnow()
    token = new_session_token()
    # Drop this student's stale sessions so the table does not grow without bound.
    db.execute(
        delete(AuthSession).where(
            AuthSession.student_id == student.id,
            or_(AuthSession.expires_at <= now, AuthSession.revoked_at.is_not(None)),
        )
    )
    db.add(
        AuthSession(
            student_id=student.id,
            token_hash=hash_session_token(token),
            created_at=now,
            expires_at=now + timedelta(seconds=settings.session_ttl_seconds),
        )
    )
    db.commit()

    class_name = db.scalar(select(SchoolClass.name).where(SchoolClass.id == student.class_id))
    log_event(logger, "login_succeeded", student_id=student.id)
    return LoginResponse(
        access_token=token,
        expires_in=settings.session_ttl_seconds,
        student=StudentSummary(id=student.id, full_name=student.full_name, class_name=class_name),
    )


@router.post("/auth/logout", status_code=204)
def logout(auth: Auth = Depends(get_auth), db: Session = Depends(get_db)) -> Response:
    session = db.get(AuthSession, auth.session.id)
    if session is not None and session.revoked_at is None:
        session.revoked_at = utcnow()
        db.commit()
    log_event(logger, "logout", student_id=auth.student.id)
    return Response(status_code=204)


@router.get("/me", response_model=MeResponse)
def me(auth: Auth = Depends(get_auth), db: Session = Depends(get_db)) -> MeResponse:
    student = auth.student
    school_class = db.get(SchoolClass, student.class_id) if student.class_id else None
    return MeResponse(
        id=student.id,
        student_code=student.student_code,
        username=student.username,
        full_name=student.full_name,
        school_class=ClassInfo(id=school_class.id, name=school_class.name) if school_class else None,
    )
