"""Test fixtures. Tests use in-memory SQLite; the upsert path is dialect-aware.

The full stack (PostgreSQL + Nginx) is exercised by deploy/scripts/smoke_test.py.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

VIDEO_ROOT = Path(tempfile.mkdtemp(prefix="lms-test-videos-"))
os.environ.update(
    {
        "DATABASE_URL": "sqlite://",
        "MEDIA_SIGNING_SECRET": "test-signing-secret-0123456789abcdefghijklmnop",
        "VIDEO_ROOT": str(VIDEO_ROOT),
        "MEDIA_BASE_URL": "",
        "LOG_LEVEL": "WARNING",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Chapter,
    SchoolClass,
    Student,
    Subject,
    Video,
    VideoStatus,
)
from app.security import hash_password  # noqa: E402

from .mp4_builder import build_mp4  # noqa: E402

PASSWORD = "Correct-Horse-42"


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def db(session_factory) -> Session:
    with session_factory() as session:
        yield session


@pytest.fixture
def settings():
    return get_settings()


@pytest.fixture
def client(session_factory, settings):
    def _get_db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def write_video(storage_key: str, **kwargs) -> Path:
    path = VIDEO_ROOT.joinpath(*storage_key.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_mp4(**kwargs))
    return path


@dataclass
class Catalog:
    class12: SchoolClass
    class11: SchoolClass
    cs: Subject
    maths_inactive: Subject
    physics: Subject
    basics: Chapter
    advanced: Chapter
    unpublished_chapter: Chapter
    motion: Chapter
    lesson1: Video
    lesson2: Video
    draft: Video
    archived: Video
    in_unpublished_chapter: Video
    in_inactive_subject: Video
    missing_file: Video
    class11_video: Video
    student: Student
    student2: Student
    class11_student: Student
    inactive: Student
    unassigned: Student


@pytest.fixture
def catalog(db) -> Catalog:
    class12 = SchoolClass(name="Class 12")
    class11 = SchoolClass(name="Class 11")
    db.add_all([class12, class11])
    db.flush()

    cs = Subject(class_id=class12.id, name="Computer Science", sort_order=1)
    maths_inactive = Subject(class_id=class12.id, name="Old Maths", sort_order=2, is_active=False)
    physics = Subject(class_id=class11.id, name="Physics", sort_order=1)
    db.add_all([cs, maths_inactive, physics])
    db.flush()

    advanced = Chapter(subject_id=cs.id, title="Advanced", sort_order=2, is_published=True)
    basics = Chapter(subject_id=cs.id, title="Basics", sort_order=1, is_published=True)
    unpublished_chapter = Chapter(subject_id=cs.id, title="Coming Soon", sort_order=3, is_published=False)
    old_chapter = Chapter(subject_id=maths_inactive.id, title="Algebra", is_published=True)
    motion = Chapter(subject_id=physics.id, title="Motion", is_published=True)
    db.add_all([advanced, basics, unpublished_chapter, old_chapter, motion])
    db.flush()

    def video(chapter, title, key, status=VideoStatus.PUBLISHED, sort=0, duration=600, file=True):
        if file:
            write_video(key, duration_seconds=duration)
        v = Video(
            chapter_id=chapter.id,
            title=title,
            storage_key=key,
            duration_seconds=duration,
            status=status.value,
            sort_order=sort,
        )
        db.add(v)
        return v

    lesson2 = video(basics, "Lesson 2", "class12/cs/lesson-02.mp4", sort=2)
    lesson1 = video(basics, "Lesson 1", "class12/cs/lesson-01.mp4", sort=1, duration=1200)
    draft = video(basics, "Draft", "class12/cs/draft.mp4", status=VideoStatus.DRAFT, sort=3)
    archived = video(basics, "Archived", "class12/cs/archived.mp4", status=VideoStatus.ARCHIVED, sort=4)
    missing_file = video(advanced, "Missing", "class12/cs/missing.mp4", file=False)
    in_unpublished = video(unpublished_chapter, "Hidden", "class12/cs/hidden.mp4")
    in_inactive = video(old_chapter, "Old", "class12/maths/old.mp4")
    class11_video = video(motion, "Speed", "class11/physics/speed.mp4")

    def student(code, username, school_class, active=True):
        s = Student(
            student_code=code,
            username=username,
            full_name=username.title(),
            password_hash=hash_password(PASSWORD),
            class_id=school_class.id if school_class else None,
            is_active=active,
        )
        db.add(s)
        return s

    students = [
        student("S12-001", "demo.student", class12),
        student("S12-002", "demo.student2", class12),
        student("S11-001", "demo.class11", class11),
        student("S12-099", "demo.inactive", class12, active=False),
        student("S00-001", "demo.unassigned", None),
    ]
    db.commit()
    return Catalog(
        class12, class11, cs, maths_inactive, physics, basics, advanced, unpublished_chapter,
        motion, lesson1, lesson2, draft, archived, in_unpublished, in_inactive, missing_file,
        class11_video, *students,
    )


def login(client: TestClient, username: str, password: str = PASSWORD) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
