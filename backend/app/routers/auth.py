"""Local sign-in and sign-out (FR-01). No external identity provider."""

from __future__ import annotations

import logging
import math
import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Response
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..deps import Auth, get_auth
from ..errors import ApiError
from ..logging_config import log_event
from ..models import AuthSession, Batch, LoginThrottle, SchoolClass, Student, as_utc, utcnow
from ..schemas import LoginRequest, LoginResponse, MeResponse, NamedRef, StudentSummary
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


def _throttle_key(student: Student | None, identifier: str) -> str:
    """One count per account, whichever name it was typed as; else per typed name."""
    if student is not None:
        return f"student:{student.id}"
    return "name:" + identifier.strip().lower().replace("\x00", "")[:100]


def _lock_seconds_left(db: Session, key: str, now: datetime) -> int:
    row = db.get(LoginThrottle, key)
    if row is None or row.locked_until is None:
        return 0
    return max(0, math.ceil((as_utc(row.locked_until) - now).total_seconds()))


def _record_failure(db: Session, key: str, now: datetime, settings: Settings) -> None:
    """Count a wrong password; lock the account at LOGIN_MAX_FAILURES within the window."""
    window = timedelta(seconds=settings.login_lock_seconds)
    row = db.get(LoginThrottle, key)
    if row is None:
        row = LoginThrottle(key=key, failures=0, first_failed_at=now)
        db.add(row)
        if random.random() < 0.01:  # now and then, forget streaks that ended long ago
            stale = now - max(window, timedelta(days=1))
            db.execute(
                delete(LoginThrottle).where(
                    LoginThrottle.first_failed_at < stale,
                    func.coalesce(LoginThrottle.locked_until, LoginThrottle.first_failed_at) < now,
                )
            )
    elif as_utc(row.first_failed_at) + window <= now:  # an old streak: count afresh
        row.failures, row.first_failed_at, row.locked_until = 0, now, None
    row.failures += 1
    if row.failures >= settings.login_max_failures:
        row.locked_until = now + window
    try:
        db.commit()
    except IntegrityError:  # the same name failed twice at once; one count is enough
        db.rollback()


def _too_many_attempts(seconds: int) -> ApiError:
    minutes = max(1, math.ceil(seconds / 60))
    return ApiError(
        429,
        "too_many_attempts",
        f"Too many wrong passwords for this account. Try again in {minutes} minute{'' if minutes == 1 else 's'}.",
        headers={"Retry-After": str(seconds)},
    )


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
    key = _throttle_key(student, body.username)
    now = utcnow()
    # A locked account is refused even with the right password, so guessing cannot go on.
    if (wait := _lock_seconds_left(db, key, now)) > 0:
        log_event(logger, "login_failed", logging.WARNING, reason="locked",
                  student_id=student.id if student else None)
        raise _too_many_attempts(wait)
    if student is None:
        burn_dummy_verification(body.password)
        _record_failure(db, key, now, settings)
        log_event(logger, "login_failed", logging.WARNING, reason="unknown_user")
        raise _invalid_credentials()
    if not verify_password(student.password_hash, body.password):
        _record_failure(db, key, now, settings)
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

    db.execute(delete(LoginThrottle).where(LoginThrottle.key == key))
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

    row = db.execute(
        select(SchoolClass.name, Batch.name)
        .join(Batch, SchoolClass.batch_id == Batch.id)
        .where(SchoolClass.id == student.class_id)
    ).first()
    class_name, batch_name = row if row else (None, None)
    log_event(logger, "login_succeeded", student_id=student.id)
    return LoginResponse(
        access_token=token,
        expires_in=settings.session_ttl_seconds,
        student=StudentSummary(
            id=student.id, full_name=student.full_name, class_name=class_name, batch_name=batch_name
        ),
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
    batch = db.get(Batch, school_class.batch_id) if school_class else None
    return MeResponse(
        id=student.id,
        student_code=student.student_code,
        username=student.username,
        full_name=student.full_name,
        school_class=NamedRef(id=school_class.id, name=school_class.name) if school_class else None,
        batch=NamedRef(id=batch.id, name=batch.name) if batch else None,
    )
