from sqlalchemy import func, select

from app.config import get_settings
from app.main import app
from app.models import ContentProgress as StudentVideoProgress

from .conftest import login


def test_progress_defaults_to_zero(client, catalog):
    headers = login(client, "demo.student")
    body = client.get(f"/api/v1/videos/{catalog.lesson1.id}/progress", headers=headers).json()
    assert body["position_seconds"] == 0
    assert body["is_completed"] is False
    assert body["last_watched_at"] is None


def test_save_and_read_progress(client, catalog):  # AC-09
    headers = login(client, "demo.student")
    saved = client.put(
        f"/api/v1/videos/{catalog.lesson1.id}/progress",
        json={"position_seconds": 765.4, "duration_seconds": 1200, "is_completed": False},
        headers=headers,
    )
    assert saved.status_code == 200
    assert saved.json()["position_seconds"] == 765
    assert saved.json()["last_watched_at"]

    # A new session (app restart) reads the same progress.
    again = client.get(
        f"/api/v1/videos/{catalog.lesson1.id}/progress", headers=login(client, "demo.student")
    ).json()
    assert again["position_seconds"] == 765


def test_retries_do_not_duplicate_rows(client, catalog, db):  # T-18
    headers = login(client, "demo.student")
    for position in (10, 20, 20, 30):
        client.put(
            f"/api/v1/videos/{catalog.lesson1.id}/progress",
            json={"position_seconds": position},
            headers=headers,
        )
    count = db.scalar(select(func.count()).select_from(StudentVideoProgress))
    assert count == 1
    body = client.get(f"/api/v1/videos/{catalog.lesson1.id}/progress", headers=headers).json()
    assert body["position_seconds"] == 30


def test_completion_threshold_and_completion_is_sticky(client, catalog):
    headers = login(client, "demo.student")
    url = f"/api/v1/videos/{catalog.lesson1.id}/progress"  # 1200 s long
    assert client.put(url, json={"position_seconds": 1000}, headers=headers).json()["is_completed"] is False
    assert client.put(url, json={"position_seconds": 1080}, headers=headers).json()["is_completed"] is True
    rewatch = client.put(url, json={"position_seconds": 60}, headers=headers).json()
    assert rewatch["is_completed"] is True
    assert rewatch["position_seconds"] == 60


def test_threshold_zero_disables_automatic_completion(client, catalog, settings):
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(update={"completion_threshold": 0})
    headers = login(client, "demo.student")
    url = f"/api/v1/videos/{catalog.lesson1.id}/progress"
    assert client.put(url, json={"position_seconds": 1199}, headers=headers).json()["is_completed"] is False
    assert client.put(url, json={"position_seconds": 1199, "is_completed": True}, headers=headers).json()["is_completed"] is True


def test_position_is_clamped_to_duration(client, catalog):
    headers = login(client, "demo.student")
    body = client.put(
        f"/api/v1/videos/{catalog.lesson1.id}/progress", json={"position_seconds": 99999}, headers=headers
    ).json()
    assert body["position_seconds"] == 1200


def test_student_identity_comes_from_the_token(client, catalog):
    headers = login(client, "demo.student")
    client.put(
        f"/api/v1/videos/{catalog.lesson1.id}/progress",
        json={"position_seconds": 300, "student_id": str(catalog.student2.id)},
        headers=headers,
    )
    other = client.get(
        f"/api/v1/videos/{catalog.lesson1.id}/progress", headers=login(client, "demo.student2")
    ).json()
    assert other["position_seconds"] == 0


def test_progress_for_inaccessible_video_is_rejected(client, catalog):
    headers = login(client, "demo.student")
    for video in (catalog.draft, catalog.class11_video):
        response = client.put(
            f"/api/v1/videos/{video.id}/progress", json={"position_seconds": 5}, headers=headers
        )
        assert response.status_code == 404


def test_invalid_position_is_rejected(client, catalog):
    headers = login(client, "demo.student")
    response = client.put(
        f"/api/v1/videos/{catalog.lesson1.id}/progress", json={"position_seconds": -1}, headers=headers
    )
    assert response.status_code == 422
