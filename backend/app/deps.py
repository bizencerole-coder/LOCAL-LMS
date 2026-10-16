"""Request dependencies: authenticated student."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .errors import unauthorized
from .models import AuthSession, Student, as_utc, utcnow
from .security import hash_session_token

_bearer = HTTPBearer(auto_error=False)


@dataclass
class Auth:
    student: Student
    session: AuthSession


def get_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Auth:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized("Please sign in.")

    row = db.execute(
        select(AuthSession, Student)
        .join(Student, AuthSession.student_id == Student.id)
        .where(AuthSession.token_hash == hash_session_token(credentials.credentials))
    ).first()
    if row is None:
        raise unauthorized()
    session, student = row
    if (
        session.revoked_at is not None
        or as_utc(session.expires_at) <= utcnow()
        or not student.is_active
    ):
        raise unauthorized()

    request.state.student_id = str(student.id)
    return Auth(student=student, session=session)


def get_student(auth: Auth = Depends(get_auth)) -> Student:
    return auth.student
