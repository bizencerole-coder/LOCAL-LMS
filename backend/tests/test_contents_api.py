"""The current student API: subjects -> modules -> contents (videos, notes, images)."""

from urllib.parse import parse_qs, urlsplit

from sqlalchemy import select

from app.models import ContentProgress

from .conftest import login
from .test_playback import nginx_secure_link_ok


def test_subject_counts_by_type(client, catalog):
    subjects = client.get("/api/v1/subjects", headers=login(client, "demo.student")).json()
    assert [s["name"] for s in subjects] == ["Computer Science"]
    cs = subjects[0]
    # Basics + Advanced published; Coming Soon is not.
    assert cs["module_count"] == cs["chapter_count"] == 2
    # Lesson 1, Lesson 2, Missing; plus the notes and the diagram.
    assert (cs["video_count"], cs["notes_count"], cs["image_count"], cs["content_count"]) == (3, 1, 1, 5)


def test_modules_are_published_and_ordered_with_counts(client, catalog):
    headers = login(client, "demo.student")
    modules = client.get(f"/api/v1/subjects/{catalog.cs.id}/modules", headers=headers).json()
    assert [m["title"] for m in modules] == ["Basics", "Advanced"]
    assert (modules[0]["video_count"], modules[0]["notes_count"], modules[0]["image_count"]) == (2, 1, 1)
    assert modules[0]["content_count"] == 4


def test_contents_list_all_types_in_order_without_storage_keys(client, catalog):
    headers = login(client, "demo.student")
    items = client.get(f"/api/v1/modules/{catalog.basics.id}/contents", headers=headers).json()
    assert [(i["title"], i["type"]) for i in items] == [
        ("Lesson 1", "video"),
        ("Lesson 2", "video"),
        ("Basics notes", "pdf"),
        ("Diagram", "image"),
    ]
    assert items[2]["file_size_bytes"] > 0 and items[2]["duration_seconds"] is None
    assert all("storage_key" not in i for i in items)


def test_other_class_inactive_batch_and_unpublished_are_not_found(client, catalog):
    headers = login(client, "demo.student")
    for subject in (catalog.physics, catalog.maths_inactive, catalog.old_subject):
        assert client.get(f"/api/v1/subjects/{subject.id}/modules", headers=headers).status_code == 404
    for module in (catalog.unpublished_chapter, catalog.motion, catalog.old_module):
        assert client.get(f"/api/v1/modules/{module.id}/contents", headers=headers).status_code == 404


def test_inactive_batch_hides_its_classes(client, catalog, db):
    headers = login(client, "old.student")
    assert client.get("/api/v1/subjects", headers=headers).json() == []
    assert client.post(f"/api/v1/contents/{catalog.in_inactive_batch.id}/open", headers=headers).status_code == 404
    catalog.old_batch.is_active = True
    db.commit()
    assert [s["name"] for s in client.get("/api/v1/subjects", headers=headers).json()] == ["Computer Science"]


def test_content_detail(client, catalog):
    headers = login(client, "demo.student")
    body = client.get(f"/api/v1/contents/{catalog.notes.id}", headers=headers).json()
    assert (body["type"], body["module_title"], body["subject_name"]) == ("pdf", "Basics", "Computer Science")
    assert client.get(f"/api/v1/contents/{catalog.draft.id}", headers=headers).status_code == 404


def test_open_video_gives_a_signed_url_and_resume_point(client, catalog, settings):
    headers = login(client, "demo.student")
    client.put(f"/api/v1/contents/{catalog.lesson1.id}/progress", json={"position_seconds": 300}, headers=headers)
    body = client.post(f"/api/v1/contents/{catalog.lesson1.id}/open", headers=headers).json()
    assert body["type"] == "video" and body["mime_type"] == "video/mp4"
    assert body["resume_position_seconds"] == 300 and body["is_completed"] is False
    assert nginx_secure_link_ok(body["url"], settings.media_signing_secret)
    assert parse_qs(urlsplit(body["url"]).query)["sid"] == [str(catalog.student.id)]


def test_open_notes_records_them_as_viewed(client, catalog, settings, db):
    headers = login(client, "demo.student")
    body = client.post(f"/api/v1/contents/{catalog.notes.id}/open", headers=headers).json()
    assert body["type"] == "pdf" and body["mime_type"] == "application/pdf"
    assert urlsplit(body["url"]).path.endswith("/01-basics/notes.pdf")
    assert nginx_secure_link_ok(body["url"], settings.media_signing_secret)
    assert body["is_completed"] is True
    progress = db.scalar(select(ContentProgress).where(ContentProgress.content_id == catalog.notes.id))
    assert progress.is_completed and progress.student_id == catalog.student.id

    image = client.post(f"/api/v1/contents/{catalog.diagram.id}/open", headers=headers).json()
    assert image["type"] == "image" and image["mime_type"] == "image/png"


def test_open_is_denied_for_hidden_items_and_missing_files(client, catalog):
    headers = login(client, "demo.student")
    for item in (catalog.draft, catalog.archived, catalog.in_unpublished_chapter, catalog.class11_video):
        assert client.post(f"/api/v1/contents/{item.id}/open", headers=headers).status_code == 404
    missing = client.post(f"/api/v1/contents/{catalog.missing_file.id}/open", headers=headers)
    assert missing.status_code == 503 and missing.json()["error"]["code"] == "media_unavailable"
    assert client.post(f"/api/v1/contents/{catalog.lesson1.id}/open").status_code == 401


def test_content_progress_round_trip(client, catalog):
    headers = login(client, "demo.student")
    url = f"/api/v1/contents/{catalog.lesson1.id}/progress"
    assert client.get(url, headers=headers).json()["position_seconds"] == 0
    saved = client.put(url, json={"position_seconds": 1150, "duration_seconds": 1200}, headers=headers).json()
    assert saved["content_id"] == str(catalog.lesson1.id)
    assert saved["is_completed"] is True  # past 90 %
    assert client.get(url, headers=headers).json()["position_seconds"] == 1150


def test_continue_lists_in_progress_and_everything_recent(client, catalog):
    headers = login(client, "demo.student")
    client.put(f"/api/v1/contents/{catalog.lesson1.id}/progress", json={"position_seconds": 30}, headers=headers)
    client.post(f"/api/v1/contents/{catalog.notes.id}/open", headers=headers)
    in_progress = client.get("/api/v1/me/continue", headers=headers).json()
    assert [i["content"]["title"] for i in in_progress] == ["Lesson 1"]
    assert in_progress[0]["module_title"] == "Basics" and in_progress[0]["subject_name"] == "Computer Science"
    everything = client.get("/api/v1/me/continue?include_completed=true", headers=headers).json()
    assert [i["content"]["title"] for i in everything] == ["Basics notes", "Lesson 1"]
    # The legacy list only ever shows videos.
    assert [r["video"]["title"] for r in client.get("/api/v1/me/recent", headers=headers).json()] == ["Lesson 1"]


def test_legacy_endpoints_never_return_notes_or_images(client, catalog):
    headers = login(client, "demo.student")
    videos = client.get(f"/api/v1/chapters/{catalog.basics.id}/videos", headers=headers).json()
    assert [v["title"] for v in videos] == ["Lesson 1", "Lesson 2"]
    assert client.post(f"/api/v1/videos/{catalog.notes.id}/playback", headers=headers).status_code == 404
    assert client.get(f"/api/v1/videos/{catalog.diagram.id}", headers=headers).status_code == 404


def test_subjects_and_modules_count_what_the_student_completed(client, catalog):
    headers = login(client, "demo.student")
    client.put(f"/api/v1/contents/{catalog.lesson1.id}/progress", json={"position_seconds": 1190}, headers=headers)
    client.put(f"/api/v1/contents/{catalog.lesson2.id}/progress", json={"position_seconds": 30}, headers=headers)
    client.post(f"/api/v1/contents/{catalog.notes.id}/open", headers=headers)
    subjects = client.get("/api/v1/subjects", headers=headers).json()
    assert subjects[0]["completed_count"] == 2  # lesson 1 watched, notes opened; lesson 2 only started
    modules = client.get(f"/api/v1/subjects/{catalog.cs.id}/modules", headers=headers).json()
    assert [(m["title"], m["completed_count"]) for m in modules] == [("Basics", 2), ("Advanced", 0)]
    # Another student's progress is not counted.
    other = client.get("/api/v1/subjects", headers=login(client, "demo.student2")).json()
    assert other[0]["completed_count"] == 0
