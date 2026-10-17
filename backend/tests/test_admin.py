"""The staff web dashboard (/admin)."""

import re
import uuid

import pytest
from sqlalchemy import select

from app.models import (
    AuthSession,
    Batch,
    Content,
    ContentProgress,
    Module,
    SchoolClass,
    StaffSession,
    StaffUser,
    Student,
    Subject,
    SyncRun,
)
from app.security import hash_password, verify_password

from .conftest import BATCH, VIDEO_ROOT, login, pdf_bytes, png_bytes, write_video
from .mp4_builder import build_mp4

STAFF_PW = "Staff-Password-9"


def make_staff(db, username="teacher", role="staff", active=True) -> StaffUser:
    member = StaffUser(username=username, full_name=username.title(), password_hash=hash_password(STAFF_PW),
                       role=role, is_active=active)
    db.add(member)
    db.commit()
    return member


def sign_in(client, username: str) -> str:
    """Signs the test client in; returns the page's CSRF token."""
    response = client.post("/admin/login", data={"username": username, "password": STAFF_PW, "next": "/admin/"})
    assert response.status_code == 200, response.text
    return csrf_of(client.get("/admin/").text)


def csrf_of(html: str) -> str:
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


@pytest.fixture
def admin(client, db):
    make_staff(db, "principal", role="admin")
    return sign_in(client, "principal")


@pytest.fixture
def teacher(client, db):
    make_staff(db, "teacher")
    return sign_in(client, "teacher")


def post(client, url, csrf, **data):
    return client.post(url, data={"csrf_token": csrf, **data}, follow_redirects=False)


# --------------------------------------------------------------------------- sign-in and protection


def test_pages_need_a_staff_session(client, db):
    response = client.get("/admin/batches", follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"].startswith("/admin/login?next=/admin/batches")
    assert client.get("/", follow_redirects=False).headers["location"] == "/admin/"
    upload = client.put(f"/admin/upload/{uuid.uuid4()}?filename=a.mp4", content=b"x")
    assert upload.status_code == 401 and upload.json()["ok"] is False


def test_login_logout_and_bad_passwords(client, db):
    make_staff(db, "teacher")
    make_staff(db, "gone", active=False)
    page = client.get("/admin/login")
    assert page.status_code == 200 and "Content-Security-Policy" in page.headers
    for username, password in (("teacher", "wrong-password"), ("nobody", STAFF_PW), ("gone", STAFF_PW)):
        bad = client.post("/admin/login", data={"username": username, "password": password})
        assert bad.status_code == 401 and "Incorrect username or password" in bad.text
    ok = client.post("/admin/login", data={"username": "Teacher", "password": STAFF_PW}, follow_redirects=False)
    assert ok.status_code == 303
    cookie = ok.headers["set-cookie"]
    assert "lms_staff=" in cookie and "HttpOnly" in cookie and "Path=/admin" in cookie
    assert "samesite=strict" in cookie.lower()
    dashboard = client.get("/admin/")
    assert dashboard.status_code == 200 and "Hello, Teacher" in dashboard.text
    assert dashboard.headers["Cache-Control"] == "no-store"
    csrf = csrf_of(dashboard.text)
    assert post(client, "/admin/logout", csrf).status_code == 303
    assert client.get("/admin/", follow_redirects=False).status_code == 303
    # An open redirect through ?next= is not possible.
    client.post("/admin/login", data={"username": "teacher", "password": STAFF_PW})
    hop = client.post("/admin/login", data={"username": "teacher", "password": STAFF_PW, "next": "//evil.example/"},
                      follow_redirects=False)
    assert hop.headers["location"] == "/admin/"


def test_posts_need_csrf_and_same_origin(client, db, teacher):
    assert post(client, "/admin/batches", "wrong", name="X").status_code == 403
    assert client.post("/admin/batches", data={"name": "X"}).status_code == 403
    foreign = client.post("/admin/batches", data={"csrf_token": teacher, "name": "X"},
                          headers={"Origin": "http://evil.example"})
    assert foreign.status_code == 403
    assert db.scalar(select(Batch).where(Batch.name == "X")) is None


def test_staff_pages_are_for_admins_only(client, db, teacher):
    assert client.get("/admin/staff").status_code == 403
    assert post(client, "/admin/staff", teacher, username="x", full_name="X", role="admin",
                password="password-1", password_confirm="password-1").status_code == 403


# --------------------------------------------------------------------------- content tree


def test_create_the_tree_with_matching_folders(client, db, teacher):
    name = f"NEET {uuid.uuid4().hex[:6]}"
    response = post(client, "/admin/batches", teacher, name=name, description="Entrance coaching")
    assert response.status_code == 303
    batch = db.scalar(select(Batch).where(Batch.name == name))
    assert batch.folder.startswith("neet-")
    assert (VIDEO_ROOT / batch.folder / "title.txt").read_text().strip() == name

    post(client, f"/admin/batches/{batch.id}/classes", teacher, name="Class 12 – Bio")
    school_class = db.scalar(select(SchoolClass).where(SchoolClass.batch_id == batch.id))
    assert school_class.folder == "class-12-bio"
    post(client, f"/admin/classes/{school_class.id}/subjects", teacher, name="Biology", folder="bio")
    subject = db.scalar(select(Subject).where(Subject.class_id == school_class.id))
    post(client, f"/admin/subjects/{subject.id}/modules", teacher, title="Cell Structure", is_published="1")
    module = db.scalar(select(Module).where(Module.subject_id == subject.id))
    assert module.folder == "01-cell-structure" and module.is_published
    folder = VIDEO_ROOT / batch.folder / "class-12-bio" / "bio" / "01-cell-structure"
    assert (folder / "title.txt").read_text().strip() == "Cell Structure"

    for url in (f"/admin/batches/{batch.id}", f"/admin/classes/{school_class.id}", f"/admin/subjects/{subject.id}",
                f"/admin/modules/{module.id}", "/admin/batches"):
        page = client.get(url)
        assert page.status_code == 200, url
    assert "Cell Structure" in client.get(f"/admin/subjects/{subject.id}").text

    # Renaming changes the name and title.txt, never the folder.
    post(client, f"/admin/modules/{module.id}", teacher, title="Cells", is_published="1")
    db.refresh(module)
    assert (module.title, module.folder) == ("Cells", "01-cell-structure")
    assert (folder / "title.txt").read_text().strip() == "Cells"

    # Duplicates and bad folder names are refused with a message.
    dup = post(client, f"/admin/subjects/{subject.id}/modules", teacher, title="Cells")
    assert dup.status_code == 303
    assert "already has a module" in client.get(dup.headers["location"]).text
    bad = post(client, f"/admin/subjects/{subject.id}/modules", teacher, title="Other", folder="../x")
    assert bad.status_code == 303
    assert db.scalar(select(Module).where(Module.title == "Other")) is None

    # Deleting: only empty items; the folder goes with it.
    post(client, f"/admin/batches/{batch.id}/delete", teacher)
    db.expire_all()
    assert db.scalar(select(Batch).where(Batch.id == batch.id)) is not None
    module_id = module.id
    post(client, f"/admin/modules/{module_id}/delete", teacher)
    db.expire_all()
    assert db.scalar(select(Module).where(Module.id == module_id)) is None and not folder.exists()


def _upload(client, csrf, module_id, name, body, **params):
    query = "&".join(f"{k}={v}" for k, v in {"filename": name, **params}.items())
    return client.put(f"/admin/upload/{module_id}?{query}", content=body,
                      headers={"X-CSRF-Token": csrf, "Content-Type": "application/octet-stream"})


def test_upload_video_notes_and_image(client, db, catalog, teacher):
    video = _upload(client, teacher, catalog.basics.id, "Recursion Explained.mp4",
                    build_mp4(duration_seconds=95), publish="true")
    assert video.status_code == 200, video.text
    body = video.json()
    assert (body["ok"], body["type"], body["status"], body["title"]) == (True, "video", "published", "Recursion Explained")
    item = db.get(Content, uuid.UUID(body["id"]))
    assert item.storage_key == f"{BATCH}/class12/cs/01-basics/07-recursion-explained.mp4"
    assert item.duration_seconds == 95 and item.checksum and item.sort_order == 7
    path = VIDEO_ROOT.joinpath(*item.storage_key.split("/"))
    assert path.is_file() and path.with_suffix(".txt").read_text().strip() == "Recursion Explained"
    assert not any((VIDEO_ROOT / ".uploads").iterdir())

    notes = _upload(client, teacher, catalog.basics.id, "loops.pdf", pdf_bytes(), title="Loops: summary")
    assert notes.json()["type"] == "pdf" and notes.json()["status"] == "draft"  # not asked to publish
    image = _upload(client, teacher, catalog.basics.id, "graph.png", png_bytes(8, 6), publish="true")
    assert image.json()["type"] == "image"
    assert db.get(Content, uuid.UUID(image.json()["id"])).resolution_width == 8

    # The new items reach students straight away.
    headers = login(client, "demo.student")
    titles = [c["title"] for c in client.get(f"/api/v1/modules/{catalog.basics.id}/contents", headers=headers).json()]
    assert "Recursion Explained" in titles and "Loops: summary" not in titles


def test_upload_rejections(client, db, catalog, teacher):
    assert _upload(client, teacher, catalog.basics.id, "notes.docx", b"PK..").status_code == 400
    fake = _upload(client, teacher, catalog.basics.id, "fake.pdf", b"this is not a pdf")
    assert fake.status_code == 400 and "not a PDF" in fake.json()["error"]
    assert _upload(client, teacher, catalog.basics.id, "x.mp4", b"").status_code == 400
    assert _upload(client, teacher, uuid.uuid4(), "x.mp4", build_mp4()).status_code == 404
    assert _upload(client, "bad-token", catalog.basics.id, "x.mp4", build_mp4()).status_code == 403
    slow = _upload(client, teacher, catalog.basics.id, "slow.mp4", build_mp4(faststart=False), publish="true")
    assert slow.json()["status"] == "draft" and slow.json()["problems"]  # never auto-published with problems
    assert not [p for p in (VIDEO_ROOT / ".uploads").iterdir() if p.is_file()]


def test_publish_unpublish_archive_and_force(client, db, catalog, teacher):
    url = f"/admin/contents/{catalog.draft.id}/status"
    post(client, url, teacher, status="published")
    db.refresh(catalog.draft)
    assert catalog.draft.status == "published"
    post(client, url, teacher, status="draft")
    db.refresh(catalog.draft)
    assert catalog.draft.status == "draft"

    write_video(catalog.draft.storage_key, faststart=False)
    post(client, url, teacher, status="published")
    db.refresh(catalog.draft)
    assert catalog.draft.status == "draft"  # refused: the file has problems
    post(client, url, teacher, status="published", force="1")
    db.refresh(catalog.draft)
    assert catalog.draft.status == "published"
    write_video(catalog.draft.storage_key)  # restore

    post(client, f"/admin/contents/{catalog.missing_file.id}/status", teacher, status="draft")
    post(client, f"/admin/contents/{catalog.missing_file.id}/status", teacher, status="published")
    db.refresh(catalog.missing_file)
    assert catalog.missing_file.status == "draft"  # no file, no publishing

    page = client.get(f"/admin/contents/{catalog.lesson1.id}")
    assert page.status_code == 200 and "/media/" in page.text and "sid=staff-" in page.text


def test_move_edit_reorder_and_delete_content(client, db, catalog, teacher):
    student_headers = login(client, "demo.student")
    client.put(f"/api/v1/contents/{catalog.lesson2.id}/progress", json={"position_seconds": 40}, headers=student_headers)
    old_path = VIDEO_ROOT.joinpath(*catalog.lesson2.storage_key.split("/"))

    post(client, f"/admin/contents/{catalog.lesson2.id}", teacher, title="Lesson 2 (revised)",
         description="Now with examples", module_id=str(catalog.advanced.id))
    db.refresh(catalog.lesson2)
    assert catalog.lesson2.module_id == catalog.advanced.id
    assert catalog.lesson2.storage_key.startswith(f"{BATCH}/class12/cs/02-advanced/")
    new_path = VIDEO_ROOT.joinpath(*catalog.lesson2.storage_key.split("/"))
    assert new_path.is_file() and not old_path.exists()
    assert new_path.with_suffix(".txt").read_text().splitlines() == ["Lesson 2 (revised)", "Now with examples"]
    progress = db.scalar(select(ContentProgress).where(ContentProgress.content_id == catalog.lesson2.id))
    assert progress.position_seconds == 40  # progress kept

    # Another class's module is not a valid target.
    post(client, f"/admin/contents/{catalog.lesson1.id}", teacher, title="Lesson 1", module_id=str(catalog.motion.id))
    db.refresh(catalog.lesson1)
    assert catalog.lesson1.module_id == catalog.basics.id

    # Reorder: Lesson 1 moves one place down.
    db.expire_all()
    before = list(db.scalars(select(Content.title).where(Content.module_id == catalog.basics.id)
                             .order_by(Content.sort_order, Content.title)))
    post(client, f"/admin/contents/{catalog.lesson1.id}/move", teacher, direction="down")
    db.expire_all()
    after = list(db.scalars(select(Content.title).where(Content.module_id == catalog.basics.id)
                            .order_by(Content.sort_order, Content.title)))
    assert before[0] == "Lesson 1" and after[1] == "Lesson 1" and after[0] == before[1]
    # Delete: the row and progress go, the file goes to .trash.
    lesson2_id = catalog.lesson2.id
    post(client, f"/admin/contents/{lesson2_id}/delete", teacher)
    db.expire_all()
    assert db.scalar(select(Content).where(Content.id == lesson2_id)) is None
    assert not new_path.exists()
    assert list((VIDEO_ROOT / ".trash").rglob(new_path.name))


def test_sync_now_records_a_run(client, db, catalog, teacher):
    response = post(client, "/admin/sync", teacher, publish="1", archive_missing="")
    assert response.status_code == 303
    run = db.scalar(select(SyncRun))
    assert run.trigger == "dashboard" and run.staff_id is not None
    page = client.get(response.headers["location"])
    assert "Sync complete" in page.text


def test_dashboard_shows_stats(client, db, catalog, teacher):
    page = client.get("/admin/")
    assert page.status_code == 200
    assert "Active students" in page.text and "Recently added" in page.text


# --------------------------------------------------------------------------- students and staff


def test_student_management(client, db, catalog, teacher):
    created = post(client, "/admin/students", teacher, full_name="Anu K", username="Anu.K", student_code="s12-014",
                   class_id=str(catalog.class12.id), password="anu-password", password_confirm="anu-password")
    assert created.status_code == 303
    student = db.scalar(select(Student).where(Student.username == "anu.k"))
    assert student.student_code == "S12-014" and student.class_id == catalog.class12.id
    assert login(client, "anu.k", "anu-password")
    mismatch = post(client, "/admin/students", teacher, full_name="B", username="b", student_code="b",
                    password="12345678", password_confirm="87654321")
    assert mismatch.status_code == 303 and db.scalar(select(Student).where(Student.username == "b")) is None

    listing = client.get("/admin/students?q=anu")
    assert "Anu K" in listing.text and "Demo.Student" not in listing.text
    assert client.get(f"/admin/students/{student.id}").status_code == 200

    post(client, f"/admin/students/{student.id}/password", teacher, password="new-password-1",
         password_confirm="new-password-1")
    db.refresh(student)
    assert verify_password(student.password_hash, "new-password-1")
    assert db.scalar(select(AuthSession).where(AuthSession.student_id == student.id, AuthSession.revoked_at.is_(None))) is None

    post(client, f"/admin/students/{student.id}", teacher, full_name="Anu Kumari", username="anu.k",
         student_code="S12-014", class_id=str(catalog.class11.id))  # no is_active: deactivated
    db.refresh(student)
    assert student.full_name == "Anu Kumari" and student.class_id == catalog.class11.id and not student.is_active

    # Deleting needs an administrator.
    assert post(client, f"/admin/students/{student.id}/delete", teacher).status_code == 403


def test_csv_import(client, db, catalog, teacher):
    csv_text = (
        "student_code,username,full_name,class,password\n"
        "S12-100,new.one,New One,Batch 2026-27/Class 12,\n"
        "S12-101,new.two,New Two,,given-password\n"
        "S12-102,demo.student,Duplicate,,\n"
        "S12-103,new.three,New Three,No Such/Class,\n"
    )
    page = client.post("/admin/students/import",
                       data={"csrf_token": teacher, "csv_text": csv_text, "class_id": str(catalog.class11.id)})
    assert page.status_code == 200
    assert "2 students created" in page.text
    one = db.scalar(select(Student).where(Student.username == "new.one"))
    two = db.scalar(select(Student).where(Student.username == "new.two"))
    assert one.class_id == catalog.class12.id and two.class_id == catalog.class11.id
    assert verify_password(two.password_hash, "given-password")
    generated = re.search(r"S12-100,new\.one,&#34;New One&#34;,(\w+)", page.text) or re.search(
        r'S12-100,new\.one,"New One",(\w+)', page.text)
    assert generated and verify_password(one.password_hash, generated.group(1))
    assert "already exists" in page.text and "Batch not found" in page.text


def test_staff_management_keeps_an_admin(client, db, admin):
    me = db.scalar(select(StaffUser).where(StaffUser.username == "principal"))
    post(client, "/admin/staff", admin, full_name="Ravi", username="ravi", role="staff",
         password="ravi-password", password_confirm="ravi-password")
    ravi = db.scalar(select(StaffUser).where(StaffUser.username == "ravi"))
    assert ravi.role == "staff" and client.get(f"/admin/staff/{ravi.id}").status_code == 200
    # The only administrator cannot demote or deactivate themselves.
    post(client, f"/admin/staff/{me.id}", admin, full_name="Principal", role="staff", is_active="1")
    db.refresh(me)
    assert me.role == "admin"
    post(client, f"/admin/staff/{ravi.id}", admin, full_name="Ravi M", role="admin")  # deactivated
    db.refresh(ravi)
    assert ravi.role == "admin" and not ravi.is_active


def test_change_own_password(client, db, teacher):
    wrong = post(client, "/admin/account/password", teacher, current_password="nope", password="next-password-1",
                 password_confirm="next-password-1")
    assert wrong.status_code == 303
    post(client, "/admin/account/password", teacher, current_password=STAFF_PW, password="next-password-1",
         password_confirm="next-password-1")
    member = db.scalar(select(StaffUser).where(StaffUser.username == "teacher"))
    assert verify_password(member.password_hash, "next-password-1")
    # This session stays signed in.
    assert client.get("/admin/account").status_code == 200
    assert db.scalar(select(StaffSession).where(StaffSession.revoked_at.is_(None))) is not None


def test_upload_without_write_access_explains_the_fix(client, db, catalog, teacher, monkeypatch):
    from app.admin import upload as upload_module

    def refuse(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(upload_module.os, "replace", refuse)
    response = _upload(client, teacher, catalog.basics.id, "worksheet.pdf", pdf_bytes())
    assert response.status_code == 500
    assert "LMS_CONTENT_UID" in response.json()["error"]
    assert db.scalar(select(Content).where(Content.title == "Worksheet")) is None
    assert not [p for p in (VIDEO_ROOT / ".uploads").iterdir() if p.is_file()]


def test_dashboard_warns_when_content_folders_are_read_only(client, db, catalog, teacher, monkeypatch):
    import os

    real_access = os.access
    monkeypatch.setattr(os, "access", lambda path, mode, *a, **k: False if mode == os.W_OK else real_access(path, mode))
    for url in ("/admin/", f"/admin/modules/{catalog.basics.id}"):
        page = client.get(url)
        assert "The server cannot change files in" in page.text and "LMS_CONTENT_UID" in page.text, url


# --------------------------------------------------------------------------- forms as a browser sends them


def form_fields(html: str, action: str) -> dict[str, str]:
    """The hidden fields of the first form posting to ``action``, as a browser would send them."""
    match = re.search(r'<form method="post" action="' + re.escape(action) + r'"[^>]*>(.*?)</form>', html, re.S)
    assert match, f"no form for {action}"
    return dict(re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)">', match.group(1)))


def test_every_form_carries_the_page_token(client, db, catalog, admin):
    """Regression: the form helpers were imported without the page context, so every form posted an
    empty token and the dashboard answered "This form has expired" to every button."""
    pages = [
        "/admin/", "/admin/batches", f"/admin/batches/{catalog.batch.id}", f"/admin/classes/{catalog.class12.id}",
        f"/admin/subjects/{catalog.cs.id}", f"/admin/modules/{catalog.basics.id}", f"/admin/contents/{catalog.lesson1.id}",
        "/admin/students", f"/admin/students/{catalog.student.id}", "/admin/students/import", "/admin/staff",
        "/admin/account", "/admin/sync",
    ]
    for url in pages:
        html = client.get(url).text
        tokens = re.findall(r'name="csrf_token" value="([^"]*)"', html)
        assert tokens, url
        assert set(tokens) == {admin}, f"{url}: {len(tokens)} forms, tokens {set(tokens) - {admin}}"


def test_buttons_work_with_the_tokens_in_their_forms(client, db, catalog, teacher):
    module_page = client.get(f"/admin/modules/{catalog.basics.id}").text
    status_url = f"/admin/contents/{catalog.draft.id}/status"
    response = client.post(status_url, data=form_fields(module_page, status_url), follow_redirects=False)
    assert response.status_code == 303
    db.refresh(catalog.draft)
    assert catalog.draft.status == "published"

    content_page = client.get(f"/admin/contents/{catalog.lesson2.id}").text
    delete_url = f"/admin/contents/{catalog.lesson2.id}/delete"
    lesson2_id = catalog.lesson2.id
    response = client.post(delete_url, data=form_fields(content_page, delete_url), follow_redirects=False)
    assert response.status_code == 303
    db.expire_all()
    assert db.scalar(select(Content).where(Content.id == lesson2_id)) is None

    response = client.post("/admin/logout", data=form_fields(content_page, "/admin/logout"), follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == "/admin/login"
    assert client.get("/admin/", follow_redirects=False).status_code == 303
