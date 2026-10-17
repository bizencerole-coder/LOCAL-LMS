"""Staff sign-in for the web dashboard.

Sessions are opaque tokens in an HttpOnly, SameSite=Strict cookie scoped to /admin;
only a SHA-256 hash is stored (staff_sessions). Every state-changing request must
carry a CSRF token derived from the session (hidden form field or X-CSRF-Token header)
and, when the browser sends one, an Origin header for this host.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import timedelta
from urllib.parse import urlsplit

from fastapi import Depends, Request
from fastapi.responses import Response
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..logging_config import log_event
from ..models import StaffSession, StaffUser, as_utc, utcnow
from ..security import (
    burn_dummy_verification,
    hash_password,
    hash_session_token,
    new_session_token,
    password_needs_rehash,
    verify_password,
)

COOKIE = "lms_staff"
COOKIE_PATH = "/admin"
logger = logging.getLogger("app.admin")


class LoginRequired(Exception):
    """No valid dashboard session: send the browser to the sign-in page."""


class Forbidden(Exception):
    def __init__(self, message: str = "You do not have permission to do that.") -> None:
        super().__init__(message)
        self.message = message


def csrf_token_for(session_token: str, secret: str) -> str:
    key = hashlib.sha256(f"lms-admin-csrf:{secret}".encode()).digest()
    return hmac.new(key, session_token.encode(), hashlib.sha256).hexdigest()[:48]


def current_staff(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StaffUser:
    token = request.cookies.get(COOKIE, "")
    if not token or len(token) > 200:
        raise LoginRequired()
    row = db.execute(
        select(StaffSession, StaffUser)
        .join(StaffUser, StaffSession.staff_id == StaffUser.id)
        .where(StaffSession.token_hash == hash_session_token(token))
    ).first()
    if row is None:
        raise LoginRequired()
    session, staff = row
    if session.revoked_at is not None or as_utc(session.expires_at) <= utcnow() or not staff.is_active:
        raise LoginRequired()
    request.state.staff = staff
    request.state.staff_id = str(staff.id)
    request.state.staff_session_id = session.id
    request.state.csrf_token = csrf_token_for(token, settings.media_signing_secret)
    return staff


def require_admin(staff: StaffUser = Depends(current_staff)) -> StaffUser:
    if not staff.is_admin:
        raise Forbidden("Only administrators can manage staff accounts.")
    return staff


def check_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        return
    host = request.headers.get("host", "")
    if origin == "null" or urlsplit(origin).netloc.lower() != host.lower():
        log_event(logger, "admin_origin_rejected", logging.WARNING, origin=origin[:100])
        raise Forbidden("The request came from another site and was blocked.")


def check_csrf(request: Request, supplied: str | None) -> None:
    expected = getattr(request.state, "csrf_token", None)
    if not expected or not supplied or not hmac.compare_digest(expected, str(supplied)):
        log_event(logger, "admin_csrf_rejected", logging.WARNING, path=request.url.path)
        raise Forbidden("This form has expired. Reload the page and try again.")


async def posted_form(request: Request, staff: StaffUser = Depends(current_staff)):
    """The submitted form, after the origin and CSRF checks."""
    check_origin(request)
    form = await request.form()
    check_csrf(request, form.get("csrf_token"))
    return form


def authenticate(db: Session, username: str, password: str) -> StaffUser | None:
    username = username.strip().lower()
    if not username or "\x00" in username or len(username) > 100 or len(password) > 256:
        burn_dummy_verification(password)
        return None
    staff = db.scalar(select(StaffUser).where(StaffUser.username == username))
    if staff is None:
        burn_dummy_verification(password)
        log_event(logger, "admin_login_failed", logging.WARNING, reason="unknown_user")
        return None
    if not verify_password(staff.password_hash, password):
        log_event(logger, "admin_login_failed", logging.WARNING, reason="bad_password", staff_id=staff.id)
        return None
    if not staff.is_active:
        log_event(logger, "admin_login_failed", logging.WARNING, reason="inactive", staff_id=staff.id)
        return None
    if password_needs_rehash(staff.password_hash):
        staff.password_hash = hash_password(password)
    return staff


def start_session(db: Session, staff: StaffUser, settings: Settings, request: Request, response: Response) -> None:
    now = utcnow()
    token = new_session_token()
    db.execute(
        delete(StaffSession).where(
            StaffSession.staff_id == staff.id,
            or_(StaffSession.expires_at <= now, StaffSession.revoked_at.is_not(None)),
        )
    )
    db.add(
        StaffSession(
            staff_id=staff.id,
            token_hash=hash_session_token(token),
            created_at=now,
            expires_at=now + timedelta(seconds=settings.staff_session_ttl_seconds),
        )
    )
    staff.last_login_at = now
    db.commit()
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.staff_session_ttl_seconds,
        path=COOKIE_PATH,
        httponly=True,
        samesite="strict",
        secure=request.headers.get("x-forwarded-proto", request.url.scheme) == "https",
    )
    log_event(logger, "admin_login_succeeded", staff_id=staff.id)


def end_session(db: Session, request: Request, response: Response) -> None:
    session_id = getattr(request.state, "staff_session_id", None)
    if session_id is not None:
        session = db.get(StaffSession, session_id)
        if session is not None and session.revoked_at is None:
            session.revoked_at = utcnow()
            db.commit()
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
