from .conftest import login


def test_subjects_only_from_own_class_and_active(client, catalog):  # T-04, AC-02
    response = client.get("/api/v1/subjects", headers=login(client, "demo.student"))
    assert response.status_code == 200
    subjects = response.json()
    assert [s["name"] for s in subjects] == ["Computer Science"]
    # Basics + Advanced published; Coming Soon is not.
    assert subjects[0]["chapter_count"] == 2
    # Lesson 1, Lesson 2, Missing (published); not the draft/archived/hidden ones.
    assert subjects[0]["video_count"] == 3


def test_class11_student_sees_only_class11(client, catalog):
    subjects = client.get("/api/v1/subjects", headers=login(client, "demo.class11")).json()
    assert [s["name"] for s in subjects] == ["Physics"]


def test_unassigned_student_sees_nothing(client, catalog):
    assert client.get("/api/v1/subjects", headers=login(client, "demo.unassigned")).json() == []


def test_inactive_class_hides_everything(client, catalog, db):
    catalog.class12.is_active = False
    db.commit()
    assert client.get("/api/v1/subjects", headers=login(client, "demo.student")).json() == []


def test_chapters_are_published_and_ordered(client, catalog):  # T-05
    headers = login(client, "demo.student")
    chapters = client.get(f"/api/v1/subjects/{catalog.cs.id}/chapters", headers=headers).json()
    assert [c["title"] for c in chapters] == ["Basics", "Advanced"]
    assert chapters[0]["video_count"] == 2


def test_other_class_or_inactive_subject_is_not_found(client, catalog):
    headers = login(client, "demo.student")
    for subject in (catalog.physics, catalog.maths_inactive):
        response = client.get(f"/api/v1/subjects/{subject.id}/chapters", headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_videos_are_published_and_ordered(client, catalog):
    headers = login(client, "demo.student")
    videos = client.get(f"/api/v1/chapters/{catalog.basics.id}/videos", headers=headers).json()
    assert [v["title"] for v in videos] == ["Lesson 1", "Lesson 2"]
    assert videos[0]["duration_seconds"] == 1200
    assert videos[0]["progress"] is None
    assert "storage_key" not in videos[0]


def test_unpublished_chapter_videos_are_not_found(client, catalog):
    headers = login(client, "demo.student")
    response = client.get(f"/api/v1/chapters/{catalog.unpublished_chapter.id}/videos", headers=headers)
    assert response.status_code == 404


def test_video_detail(client, catalog):
    headers = login(client, "demo.student")
    body = client.get(f"/api/v1/videos/{catalog.lesson1.id}", headers=headers).json()
    assert body["title"] == "Lesson 1"
    assert body["chapter_title"] == "Basics"
    assert body["subject_name"] == "Computer Science"
    assert client.get(f"/api/v1/videos/{catalog.draft.id}", headers=headers).status_code == 404


def test_recent_lists_watched_videos_newest_first(client, catalog, db):
    headers = login(client, "demo.student")
    client.put(f"/api/v1/videos/{catalog.lesson1.id}/progress", json={"position_seconds": 30}, headers=headers)
    client.put(f"/api/v1/videos/{catalog.lesson2.id}/progress", json={"position_seconds": 600}, headers=headers)

    recent = client.get("/api/v1/me/recent", headers=headers).json()
    assert [r["video"]["title"] for r in recent] == ["Lesson 2", "Lesson 1"]
    assert recent[1]["video"]["progress"]["position_seconds"] == 30
    assert recent[0]["subject_name"] == "Computer Science"

    in_progress = client.get("/api/v1/me/recent?include_completed=false", headers=headers).json()
    assert [r["video"]["title"] for r in in_progress] == ["Lesson 1"]

    # Unpublished lessons drop out of the list.
    catalog.lesson1.status = "draft"
    db.commit()
    assert [r["video"]["title"] for r in client.get("/api/v1/me/recent", headers=headers).json()] == ["Lesson 2"]


def test_recent_is_per_student(client, catalog):
    first = login(client, "demo.student")
    client.put(f"/api/v1/videos/{catalog.lesson1.id}/progress", json={"position_seconds": 30}, headers=first)
    assert client.get("/api/v1/me/recent", headers=login(client, "demo.student2")).json() == []
