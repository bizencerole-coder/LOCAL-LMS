"""Test fixtures. Tests use in-memory SQLite; the upsert path is dialect-aware.

The full stack (PostgreSQL + Nginx) is exercised by deploy/scripts/smoke_test.py.
"""

from __future__ import annotations

import os
import struct
import tempfile
import zlib
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
    Batch,
    Content,
    ContentStatus,
    ContentType,
    Module,
    SchoolClass,
    Student,
    Subject,
)
from app.security import hash_password  # noqa: E402

from .mp4_builder import build_mp4  # noqa: E402

PASSWORD = "Correct-Horse-42"
BATCH = "batch-2026-27"


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


def _target(storage_key: str, root: Path | None = None) -> Path:
    path = (root or VIDEO_ROOT).joinpath(*storage_key.split("/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_video(storage_key: str, root: Path | None = None, **kwargs) -> Path:
    path = _target(storage_key, root)
    path.write_bytes(build_mp4(**kwargs))
    return path


def pdf_bytes(text: str = "Notes", pages: int = 1) -> bytes:
    """A small but valid PDF."""
    objects = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(pages))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>")
    font_obj = 3 + 2 * pages
    for i in range(pages):
        stream = f"BT /F1 24 Tf 72 720 Td ({text} page {i + 1}) Tj ET".encode()
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 {font_obj} 0 R >> >> >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def png_bytes(width: int = 4, height: int = 3, color: tuple[int, int, int] = (200, 30, 30)) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(color) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def write_pdf(storage_key: str, root: Path | None = None, **kwargs) -> Path:
    path = _target(storage_key, root)
    path.write_bytes(pdf_bytes(**kwargs))
    return path


def write_png(storage_key: str, root: Path | None = None, **kwargs) -> Path:
    path = _target(storage_key, root)
    path.write_bytes(png_bytes(**kwargs))
    return path


@dataclass
class Catalog:
    batch: Batch
    old_batch: Batch
    class12: SchoolClass
    class11: SchoolClass
    old_class: SchoolClass
    cs: Subject
    maths_inactive: Subject
    physics: Subject
    old_subject: Subject
    basics: Module
    advanced: Module
    unpublished_chapter: Module
    motion: Module
    old_module: Module
    lesson1: Content
    lesson2: Content
    draft: Content
    archived: Content
    in_unpublished_chapter: Content
    in_inactive_subject: Content
    missing_file: Content
    class11_video: Content
    notes: Content
    diagram: Content
    in_inactive_batch: Content
    student: Student
    student2: Student
    class11_student: Student
    inactive: Student
    unassigned: Student
    old_batch_student: Student


@pytest.fixture
def catalog(db) -> Catalog:
    batch = Batch(name="Batch 2026-27", folder=BATCH)
    old_batch = Batch(name="Batch 2025-26", folder="batch-2025-26", is_active=False)
    db.add_all([batch, old_batch])
    db.flush()

    class12 = SchoolClass(batch_id=batch.id, name="Class 12", folder="class12")
    class11 = SchoolClass(batch_id=batch.id, name="Class 11", folder="class11")
    old_class = SchoolClass(batch_id=old_batch.id, name="Class 12", folder="class12")
    db.add_all([class12, class11, old_class])
    db.flush()

    cs = Subject(class_id=class12.id, name="Computer Science", folder="cs", sort_order=1)
    maths_inactive = Subject(class_id=class12.id, name="Old Maths", folder="maths", sort_order=2, is_active=False)
    physics = Subject(class_id=class11.id, name="Physics", folder="physics", sort_order=1)
    old_subject = Subject(class_id=old_class.id, name="Computer Science", folder="cs")
    db.add_all([cs, maths_inactive, physics, old_subject])
    db.flush()

    def module(subject, title, folder, sort=0, published=True):
        m = Module(subject_id=subject.id, title=title, folder=folder, sort_order=sort, is_published=published)
        db.add(m)
        return m

    advanced = module(cs, "Advanced", "02-advanced", sort=2)
    basics = module(cs, "Basics", "01-basics", sort=1)
    unpublished_chapter = module(cs, "Coming Soon", "03-coming-soon", sort=3, published=False)
    old_chapter = module(maths_inactive, "Algebra", "algebra")
    motion = module(physics, "Motion", "motion")
    old_module = module(old_subject, "Basics", "basics")
    db.flush()

    def video(mod, title, key, status=ContentStatus.PUBLISHED, sort=0, duration=600, file=True):
        if file:
            write_video(key, duration_seconds=duration)
        v = Content(
            module_id=mod.id,
            content_type=ContentType.VIDEO.value,
            title=title,
            storage_key=key,
            duration_seconds=duration,
            status=status.value,
            sort_order=sort,
        )
        db.add(v)
        return v

    cs_key = f"{BATCH}/class12/cs"
    lesson2 = video(basics, "Lesson 2", f"{cs_key}/01-basics/lesson-02.mp4", sort=2)
    lesson1 = video(basics, "Lesson 1", f"{cs_key}/01-basics/lesson-01.mp4", sort=1, duration=1200)
    draft = video(basics, "Draft", f"{cs_key}/01-basics/draft.mp4", status=ContentStatus.DRAFT, sort=3)
    archived = video(basics, "Archived", f"{cs_key}/01-basics/archived.mp4", status=ContentStatus.ARCHIVED, sort=4)
    missing_file = video(advanced, "Missing", f"{cs_key}/02-advanced/missing.mp4", file=False)
    in_unpublished = video(unpublished_chapter, "Hidden", f"{cs_key}/03-coming-soon/hidden.mp4")
    in_inactive = video(old_chapter, "Old", f"{BATCH}/class12/maths/algebra/old.mp4")
    class11_video = video(motion, "Speed", f"{BATCH}/class11/physics/motion/speed.mp4")
    in_inactive_batch = video(old_module, "Last year", "batch-2025-26/class12/cs/basics/last-year.mp4")

    notes_key = f"{cs_key}/01-basics/notes.pdf"
    notes_path = write_pdf(notes_key, text="Basics notes", pages=2)
    notes = Content(
        module_id=basics.id,
        content_type=ContentType.PDF.value,
        mime_type="application/pdf",
        title="Basics notes",
        storage_key=notes_key,
        file_size_bytes=notes_path.stat().st_size,
        status=ContentStatus.PUBLISHED.value,
        sort_order=5,
    )
    diagram_key = f"{cs_key}/01-basics/diagram.png"
    diagram_path = write_png(diagram_key)
    diagram = Content(
        module_id=basics.id,
        content_type=ContentType.IMAGE.value,
        mime_type="image/png",
        title="Diagram",
        storage_key=diagram_key,
        file_size_bytes=diagram_path.stat().st_size,
        resolution_width=4,
        resolution_height=3,
        status=ContentStatus.PUBLISHED.value,
        sort_order=6,
    )
    db.add_all([notes, diagram])

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
        student("S25-001", "old.student", old_class),
    ]
    db.commit()
    return Catalog(
        batch, old_batch, class12, class11, old_class, cs, maths_inactive, physics, old_subject,
        basics, advanced, unpublished_chapter, motion, old_module,
        lesson1, lesson2, draft, archived, in_unpublished, in_inactive, missing_file, class11_video,
        notes, diagram, in_inactive_batch, *students,
    )


def login(client: TestClient, username: str, password: str = PASSWORD) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
