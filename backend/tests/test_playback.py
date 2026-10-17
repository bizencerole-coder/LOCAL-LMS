import base64
import hashlib
import time
from urllib.parse import parse_qs, unquote, urlsplit

from app.config import get_settings
from app.main import app

from .conftest import login


def nginx_secure_link_ok(url: str, secret: str) -> bool:
    """Re-implements Nginx's check for: secure_link_md5 "$secure_link_expires$uri$arg_sid <secret>"."""
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    expires, sid, given = query["expires"][0], query["sid"][0], query["md5"][0]
    raw = f"{expires}{unquote(parts.path)}{sid} {secret}".encode()
    expected = base64.urlsafe_b64encode(hashlib.md5(raw).digest()).rstrip(b"=").decode()
    return given == expected and int(expires) > time.time()


def test_authorized_playback_returns_signed_nginx_url(client, catalog, settings):  # AC-03
    headers = login(client, "demo.student")
    response = client.post(f"/api/v1/videos/{catalog.lesson1.id}/playback", headers=headers)
    assert response.status_code == 200
    body = response.json()
    url = body["playback_url"]
    assert url.startswith("http://testserver/media/batch-2026-27/class12/cs/01-basics/lesson-01.mp4?")
    assert nginx_secure_link_ok(url, settings.media_signing_secret)
    assert parse_qs(urlsplit(url).query)["sid"] == [str(catalog.student.id)]
    assert body["duration_seconds"] == 1200
    assert body["mime_type"] == "video/mp4"
    assert body["resume_position_seconds"] == 0


def test_tampered_url_fails_the_nginx_check(client, catalog, settings):
    headers = login(client, "demo.student")
    url = client.post(f"/api/v1/videos/{catalog.lesson1.id}/playback", headers=headers).json()["playback_url"]
    assert not nginx_secure_link_ok(url.replace("lesson-01", "lesson-02"), settings.media_signing_secret)
    assert not nginx_secure_link_ok(url, "some-other-secret")


def test_media_base_url_setting_is_used(client, catalog, settings):
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(
        update={"media_base_url": "http://lms.campus.lan"}
    )
    headers = login(client, "demo.student")
    url = client.post(f"/api/v1/videos/{catalog.lesson1.id}/playback", headers=headers).json()["playback_url"]
    assert url.startswith("http://lms.campus.lan/media/")


def test_unpublished_unassigned_and_hidden_videos_are_denied(client, catalog):  # AC-07, T-11
    headers = login(client, "demo.student")
    for video in (
        catalog.draft,
        catalog.archived,
        catalog.in_unpublished_chapter,
        catalog.in_inactive_subject,
        catalog.class11_video,
    ):
        response = client.post(f"/api/v1/videos/{video.id}/playback", headers=headers)
        assert response.status_code == 404, video.title
        assert "playback_url" not in response.text


def test_playback_requires_authentication(client, catalog):
    assert client.post(f"/api/v1/videos/{catalog.lesson1.id}/playback").status_code == 401


def test_missing_file_gives_a_clear_error(client, catalog):  # T-12
    headers = login(client, "demo.student")
    response = client.post(f"/api/v1/videos/{catalog.missing_file.id}/playback", headers=headers)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "media_unavailable"


def test_unpublishing_blocks_new_authorizations(client, catalog, db):  # T-19
    headers = login(client, "demo.student")
    assert client.post(f"/api/v1/videos/{catalog.lesson1.id}/playback", headers=headers).status_code == 200
    catalog.lesson1.status = "draft"
    db.commit()
    assert client.post(f"/api/v1/videos/{catalog.lesson1.id}/playback", headers=headers).status_code == 404


def test_playback_includes_resume_position(client, catalog):
    headers = login(client, "demo.student")
    client.put(f"/api/v1/videos/{catalog.lesson1.id}/progress", json={"position_seconds": 765}, headers=headers)
    body = client.post(f"/api/v1/videos/{catalog.lesson1.id}/playback", headers=headers).json()
    assert body["resume_position_seconds"] == 765
    assert body["is_completed"] is False
