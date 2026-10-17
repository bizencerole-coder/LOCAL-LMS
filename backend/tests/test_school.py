"""School branding, notices and home-page banners: dashboard pages and the student API."""

import re
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.branding import BRANDING_DIR
from app.config import get_settings
from app.models import Banner, Notice, SchoolProfile

from .conftest import VIDEO_ROOT, login, pdf_bytes, png_bytes
from .test_admin import admin, form_fields, make_staff, post, sign_in, teacher  # noqa: F401  (fixtures)


def _local_day(offset: int) -> str:
    today = datetime.now(ZoneInfo(get_settings().display_timezone)).date()
    return (today + timedelta(days=offset)).isoformat()


def _branding_files() -> set[str]:
    folder = VIDEO_ROOT / BRANDING_DIR
    return {p.name for p in folder.iterdir()} if folder.is_dir() else set()


def _titles(client, username: str, path: str) -> list[str]:
    return [item["title"] for item in client.get(path, headers=login(client, username)).json()]


# ------------------------------------------------------------------ school


def test_school_branding_defaults_then_admin_sets_name_colour_and_logo(client, db, admin):  # noqa: F811
    default = client.get("/api/v1/school").json()  # no sign-in: the app shows it before signing in
    assert (default["name"], default["primary_color"], default["logo_url"]) == ("Campus LMS", "#2E5AAC", None)

    logo = png_bytes(300, 300)
    response = client.post(
        "/admin/school",
        data={"csrf_token": admin, "name": "St. Mary's HSS", "short_name": "SMHSS",
              "tagline": "Learning, anywhere on campus", "primary_color": "#12a4b6"},
        files={"logo": ("logo.png", logo, "image/png")},
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    school = client.get("/api/v1/school").json()
    assert (school["name"], school["short_name"], school["primary_color"]) == ("St. Mary's HSS", "SMHSS", "#12A4B6")
    assert re.fullmatch(r"/branding/logo-[0-9a-f]{20}\.png", school["logo_url"])
    first = school["logo_url"].rsplit("/", 1)[1]
    assert (VIDEO_ROOT / BRANDING_DIR / first).read_bytes() == logo

    # A new logo replaces the file; something that is not an image is refused.
    client.post("/admin/school", data={"csrf_token": admin, "name": "St. Mary's HSS", "primary_color": "#12A4B6"},
                files={"logo": ("logo.jpg", png_bytes(256, 256, (0, 0, 0)), "image/jpeg")}, follow_redirects=False)
    second = client.get("/api/v1/school").json()["logo_url"].rsplit("/", 1)[1]
    assert second != first and first not in _branding_files() and second in _branding_files()
    client.post("/admin/school", data={"csrf_token": admin, "name": "Renamed", "primary_color": "#12A4B6"},
                files={"logo": ("logo.png", pdf_bytes(), "image/png")}, follow_redirects=False)
    client.post("/admin/school", data={"csrf_token": admin, "name": "Renamed", "primary_color": "teal"},
                follow_redirects=False)
    db.expire_all()
    profile = db.get(SchoolProfile, 1)
    assert (profile.name, profile.logo_file) == ("St. Mary's HSS", second)  # neither change was saved

    post(client, "/admin/school", admin, name="St. Mary's HSS", primary_color="#12A4B6", remove_logo="1")
    assert client.get("/api/v1/school").json()["logo_url"] is None and second not in _branding_files()


def test_only_administrators_change_the_school(client, db, teacher):  # noqa: F811
    page = client.get("/admin/school")
    assert page.status_code == 200 and "Only administrators can change these." in page.text
    response = post(client, "/admin/school", teacher, name="Taken over", primary_color="#000000")
    assert response.status_code == 403
    assert db.get(SchoolProfile, 1) is None


# ------------------------------------------------------------------ notices


def _notice(db, title: str) -> Notice:
    return db.scalar(select(Notice).where(Notice.title == title))


def test_notices_reach_the_right_students_important_first_then_newest(client, db, catalog, teacher):  # noqa: F811
    batch, class12, old_batch = catalog.batch, catalog.class12, catalog.old_batch
    for title, audience, extra in [
        ("Holiday on Friday", "all", {}),
        ("Class 12 unit test", f"class:{class12.id}", {"is_important": "1", "body": "Chapters 1-3."}),
        ("Batch picnic", f"batch:{batch.id}", {}),
        ("Old batch reunion", f"batch:{old_batch.id}", {}),
        ("Still a draft", "all", {"publish": ""}),
        ("Last week's notice", "all", {"expires_on": _local_day(-1)}),
        ("Until tomorrow", "all", {"expires_on": _local_day(1)}),
    ]:
        data = {"title": title, "audience": audience, "publish": "1", **extra}
        assert post(client, "/admin/notices", teacher, **data).status_code == 303
    # Fixed publication times, oldest first, so the order is predictable.
    start = datetime(2026, 10, 1, tzinfo=UTC)
    for minutes, title in enumerate(["Holiday on Friday", "Class 12 unit test", "Batch picnic",
                                     "Old batch reunion", "Last week's notice", "Until tomorrow"]):
        _notice(db, title).published_at = start + timedelta(minutes=minutes)
    db.commit()

    student = client.get("/api/v1/notices", headers=login(client, "demo.student")).json()
    assert [n["title"] for n in student] == ["Class 12 unit test", "Until tomorrow", "Batch picnic", "Holiday on Friday"]
    assert student[0]["is_important"] and student[0]["body"] == "Chapters 1-3."
    assert [n["audience"] for n in student] == ["Batch 2026-27 › Class 12", "All students", "Batch 2026-27", "All students"]
    assert _titles(client, "demo.class11", "/api/v1/notices") == ["Until tomorrow", "Batch picnic", "Holiday on Friday"]
    assert _titles(client, "demo.unassigned", "/api/v1/notices") == ["Until tomorrow", "Holiday on Friday"]
    assert _titles(client, "old.student", "/api/v1/notices") == ["Until tomorrow", "Old batch reunion", "Holiday on Friday"]
    assert client.get("/api/v1/notices").status_code == 401

    # Unpublish, publish again (it becomes the newest), edit, delete.
    holiday = _notice(db, "Holiday on Friday")
    post(client, f"/admin/notices/{holiday.id}/publish", teacher)
    assert "Holiday on Friday" not in _titles(client, "demo.unassigned", "/api/v1/notices")
    post(client, f"/admin/notices/{holiday.id}/publish", teacher, publish="1")
    assert _titles(client, "demo.unassigned", "/api/v1/notices")[0] == "Holiday on Friday"
    post(client, f"/admin/notices/{holiday.id}", teacher, title="Holiday on Monday", audience=f"class:{class12.id}")
    assert "Holiday on Monday" not in _titles(client, "demo.unassigned", "/api/v1/notices")
    assert "Holiday on Monday" in _titles(client, "demo.student", "/api/v1/notices")
    holiday_id = holiday.id
    post(client, f"/admin/notices/{holiday_id}/delete", teacher)
    db.expire_all()
    assert db.get(Notice, holiday_id) is None

    page = client.get("/admin/notices").text
    assert "Still a draft" in page and "Expired" in page and "Important" in page


def test_notice_form_mistakes_are_refused(client, db, catalog, teacher):  # noqa: F811
    for data in [
        {"title": "", "audience": "all"},
        {"title": "Nowhere", "audience": f"class:{uuid.uuid4()}"},
        {"title": "Bad date", "audience": "all", "expires_on": "30/11/2026"},
    ]:
        assert post(client, "/admin/notices", teacher, publish="1", **data).status_code == 303
    assert db.scalars(select(Notice)).all() == []


# ------------------------------------------------------------------ banners


def _banner(db, title: str) -> Banner:
    return db.scalar(select(Banner).where(Banner.title == title))


def _add_banner(client, csrf, title, image=None, **data):
    files = {"image": ("slide.png", image, "image/png")} if image else None
    return client.post("/admin/banners", data={"csrf_token": csrf, "title": title, "audience": "all",
                                               "is_active": "1", **data},
                       files=files, follow_redirects=False)


def test_banners_in_order_with_links_only_to_what_the_student_may_open(client, db, catalog, teacher):  # noqa: F811
    post(client, "/admin/notices", teacher, title="Exam timetable", audience="all", publish="1")
    post(client, "/admin/notices", teacher, title="Draft timetable", audience="all")
    published, draft = _notice(db, "Exam timetable"), _notice(db, "Draft timetable")

    picture = png_bytes(1600, 600)
    assert _add_banner(client, teacher, "Welcome back", subtitle="New lessons every week").status_code == 303
    _add_banner(client, teacher, "New in Computer Science", picture, link=f"subject:{catalog.cs.id}")
    _add_banner(client, teacher, "Physics: motion", link=f"module:{catalog.motion.id}")
    _add_banner(client, teacher, "See the timetable", link=f"notice:{published.id}")
    _add_banner(client, teacher, "Draft link", link=f"notice:{draft.id}")
    _add_banner(client, teacher, "Switched off", is_active="")
    _add_banner(client, teacher, "Starts tomorrow", starts_on=_local_day(1))
    _add_banner(client, teacher, "Ended yesterday", ends_on=_local_day(-1))
    _add_banner(client, teacher, "Class 11 only", audience=f"class:{catalog.class11.id}")

    headers = login(client, "demo.student")
    slides = client.get("/api/v1/banners", headers=headers).json()
    assert [s["title"] for s in slides] == [
        "Welcome back", "New in Computer Science", "Physics: motion", "See the timetable", "Draft link",
    ]
    by_title = {s["title"]: s for s in slides}
    assert by_title["Welcome back"]["subtitle"] == "New lessons every week" and by_title["Welcome back"]["link"] is None
    assert re.fullmatch(r"/branding/banner-[0-9a-f]{20}\.png", by_title["New in Computer Science"]["image_url"])
    assert by_title["New in Computer Science"]["link"] == {
        "type": "subject", "id": str(catalog.cs.id), "title": "Computer Science", "subject_id": None}
    assert by_title["Physics: motion"]["link"] is None  # a Class 11 module
    assert by_title["See the timetable"]["link"]["type"] == "notice"
    assert by_title["Draft link"]["link"] is None

    class11 = {s["title"]: s for s in client.get("/api/v1/banners", headers=login(client, "demo.class11")).json()}
    assert "Class 11 only" in class11 and class11["Physics: motion"]["link"] == {
        "type": "module", "id": str(catalog.motion.id), "title": "Motion", "subject_id": str(catalog.physics.id)}
    assert client.get("/api/v1/banners").status_code == 401

    # Order, picture removal and deletion.
    physics = _banner(db, "Physics: motion")
    post(client, f"/admin/banners/{physics.id}/move", teacher, direction="up")
    post(client, f"/admin/banners/{physics.id}/move", teacher, direction="up")
    assert _titles(client, "demo.student", "/api/v1/banners")[0] == "Physics: motion"

    cs = _banner(db, "New in Computer Science")
    image = cs.image_file
    assert image in _branding_files()
    post(client, f"/admin/banners/{cs.id}", teacher, title=cs.title, audience="all", is_active="1",
         link=f"subject:{catalog.cs.id}", remove_image="1")
    db.expire_all()
    assert _banner(db, "New in Computer Science").image_file is None and image not in _branding_files()
    post(client, f"/admin/banners/{cs.id}/delete", teacher)
    assert "New in Computer Science" not in _titles(client, "demo.student", "/api/v1/banners")

    page = client.get("/admin/banners").text
    assert "Scheduled" in page and "Ended" in page and "Off" in page


def test_banner_picture_must_be_an_image(client, db, catalog, teacher):  # noqa: F811
    response = _add_banner(client, teacher, "Not a picture", image=pdf_bytes())
    assert response.status_code == 303
    assert _banner(db, "Not a picture") is None


def test_every_new_form_carries_the_page_token(client, db, catalog, admin):  # noqa: F811
    post(client, "/admin/notices", admin, title="Exam", audience="all", publish="1")
    _add_banner(client, admin, "Welcome")
    pages = ["/admin/notices", "/admin/banners", "/admin/school",
             f"/admin/notices/{_notice(db, 'Exam').id}", f"/admin/banners/{_banner(db, 'Welcome').id}"]
    for path in pages:
        html = client.get(path).text
        token = re.search(r'<meta name="csrf-token" content="([^"]+)">', html).group(1)
        actions = re.findall(r'<form method="post" action="([^"]+)"', html)
        assert actions, path
        for action in actions:
            assert form_fields(html, action).get("csrf_token") == token, (path, action)
