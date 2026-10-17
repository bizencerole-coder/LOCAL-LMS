from datetime import timedelta

from sqlalchemy import select

from app.models import AuthSession, utcnow

from .conftest import PASSWORD, login


def test_login_success_returns_token_and_student(client, catalog):  # T-01, AC-01
    response = client.post(
        "/api/v1/auth/login", json={"username": "demo.student", "password": PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    assert body["access_token"]
    assert body["student"] == {
        "id": str(catalog.student.id),
        "full_name": catalog.student.full_name,
        "class_name": "Class 12",
        "batch_name": "Batch 2026-27",
    }
    assert response.headers["X-Request-ID"]


def test_login_accepts_student_code_and_any_case(client, catalog):
    login(client, "s12-001")
    login(client, "  Demo.Student ")


def test_wrong_password_and_unknown_user_get_the_same_error(client, catalog):  # T-02
    wrong = client.post("/api/v1/auth/login", json={"username": "demo.student", "password": "nope-nope"})
    unknown = client.post("/api/v1/auth/login", json={"username": "nobody", "password": "nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"] == unknown.json()["error"]
    assert wrong.json()["error"]["code"] == "invalid_credentials"


def test_inactive_student_is_denied(client, catalog):  # T-03
    response = client.post("/api/v1/auth/login", json={"username": "demo.inactive", "password": PASSWORD})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "account_inactive"


def test_inactive_student_with_wrong_password_gets_generic_error(client, catalog):
    response = client.post("/api/v1/auth/login", json={"username": "demo.inactive", "password": "wrong-pass"})
    assert response.status_code == 401


def test_me_requires_a_valid_token(client, catalog):
    assert client.get("/api/v1/me").status_code == 401
    bad = client.get("/api/v1/me", headers={"Authorization": "Bearer not-a-token"})
    assert bad.status_code == 401
    assert bad.headers["WWW-Authenticate"] == "Bearer"


def test_me_returns_profile(client, catalog):
    response = client.get("/api/v1/me", headers=login(client, "demo.student"))
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "demo.student"
    assert body["student_code"] == "S12-001"
    assert body["class"] == {"id": str(catalog.class12.id), "name": "Class 12"}
    assert body["batch"] == {"id": str(catalog.batch.id), "name": "Batch 2026-27"}


def test_logout_revokes_the_session(client, catalog):
    headers = login(client, "demo.student")
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 204
    assert client.get("/api/v1/me", headers=headers).status_code == 401


def test_expired_session_is_rejected(client, catalog, db):
    headers = login(client, "demo.student")
    session = db.scalar(select(AuthSession).where(AuthSession.student_id == catalog.student.id))
    session.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert client.get("/api/v1/me", headers=headers).status_code == 401


def test_deactivating_a_student_ends_existing_sessions(client, catalog, db):
    headers = login(client, "demo.student")
    catalog.student.is_active = False
    db.commit()
    assert client.get("/api/v1/me", headers=headers).status_code == 401


def test_validation_errors_use_the_error_envelope(client, catalog):
    response = client.post("/api/v1/auth/login", json={"username": ""})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
