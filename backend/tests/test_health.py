from pathlib import Path

from app.config import get_settings
from app.main import app


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_checks_database_and_storage(client):
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"database": "ok", "media_storage": "ok"}}


def test_ready_reports_missing_storage_without_leaking_paths(client, settings):
    app.dependency_overrides[get_settings] = lambda: settings.model_copy(
        update={"video_root": Path("/definitely/not/here")}
    )
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["media_storage"] == "error"
    assert "/definitely" not in response.text
