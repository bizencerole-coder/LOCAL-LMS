"""Regression tests for defects found during the 2026-10-15 full-stack review."""

import argparse
import asyncio
import json
import logging
import struct

import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import DataError
from sqlalchemy.exc import TimeoutError as SATimeoutError

from app import cli
from app.logging_config import _TextFormatter
from app.main import DbAdmission
from app.models import SchoolClass
from app.mp4info import Mp4Error, inspect_mp4
from app.routers import catalog as catalog_router

from .conftest import login
from .mp4_builder import box, build_mp4, full_box


def test_nul_in_username_is_a_normal_failed_login(client, catalog):
    response = client.post("/api/v1/auth/login", json={"username": "demo.student\u0000", "password": "x" * 8})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_unhandled_errors_keep_the_request_id(client, catalog, monkeypatch, caplog):
    headers = login(client, "demo.student")

    def boom(*args, **kwargs):
        raise RuntimeError("simulated bug")

    monkeypatch.setattr(catalog_router, "visible_subjects", boom)
    response = client.get("/api/v1/subjects", headers={**headers, "X-Request-ID": "trace-123"})
    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "trace-123"
    assert response.json()["request_id"] == "trace-123"
    assert response.json()["error"]["code"] == "internal_error"
    assert "simulated bug" not in response.text


def test_database_data_errors_are_a_400(client, catalog, monkeypatch):
    headers = login(client, "demo.student")

    def reject(*args, **kwargs):
        raise DataError("SELECT 1", {}, Exception("value out of range"))

    monkeypatch.setattr(catalog_router, "visible_subjects", reject)
    response = client.get("/api/v1/subjects", headers=headers)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_request"


def test_text_log_values_cannot_forge_fields():
    record = logging.LogRecord("app.access", logging.INFO, __file__, 1, "request", None, None)
    record.request_id = "r1"
    record.fields = {"path": '/api/v1/x student_id=evil "q"', "status": 200}
    line = _TextFormatter().format(record)
    assert 'path="/api/v1/x student_id=evil \\"q\\""' in line
    assert line.endswith("status=200")


def test_corrupt_mvhd_raises_mp4error(tmp_path):
    bad_mvhd = full_box(b"mvhd", 1, b"\x00" * 6)  # far too short for version 1
    path = tmp_path / "bad.mp4"
    path.write_bytes(box(b"ftyp", b"isom" + struct.pack(">I", 0)) + box(b"moov", bad_mvhd) + box(b"mdat", b"x"))
    with pytest.raises(Mp4Error):
        inspect_mp4(path)


def test_quicktime_data_handler_does_not_hide_the_video_track(tmp_path):
    data = bytearray(build_mp4())
    # Insert a data-handler 'hdlr' (component 'dhlr', subtype 'alis') inside minf, as QuickTime does.
    dhlr = full_box(b"hdlr", 0, b"dhlr" + b"alis" + b"\x00" * 13)
    minf = data.index(b"minf") - 4
    size = struct.unpack(">I", data[minf : minf + 4])[0]
    data[minf : minf + size] = box(b"minf", bytes(data[minf + 8 : minf + size]) + dhlr)
    # Fix up the parent sizes (mdia, trak, moov) for the inserted bytes.
    for parent in (b"mdia", b"trak", b"moov"):
        start = data.index(parent) - 4
        old = struct.unpack(">I", data[start : start + 4])[0]
        data[start : start + 4] = struct.pack(">I", old + len(dhlr))
    path = tmp_path / "qt.mov.mp4"
    path.write_bytes(bytes(data))
    info = inspect_mp4(path)
    assert info.video_track is not None and info.video_track.codec == "avc1"
    assert info.problems() == []


def test_seed_demo_rerun_with_untrimmed_names(db, tmp_path, monkeypatch):
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps({
        "classes": [{"name": " Padded Class ", "subjects": [{"name": " CS ", "chapters": [{"title": " Intro "}]}]}],
    }))
    args = argparse.Namespace(manifest=str(manifest), password_env=None, password_stdin=False)
    cli.cmd_seed_demo(db, args)
    db.flush()
    cli.cmd_seed_demo(db, args)
    db.flush()
    assert db.scalar(select(func.count()).select_from(SchoolClass).where(SchoolClass.name == "Padded Class")) == 1


def test_admission_gate_answers_503_instead_of_queueing_forever():
    """A burst larger than the pool must not stall the worker (live probe L0)."""

    async def scenario():
        release = asyncio.Event()

        async def slow_app(scope, receive, send):
            if scope["path"] != "/health":
                await release.wait()
            await JSONResponse({"ok": True})(scope, receive, send)

        gate = DbAdmission(slow_app, limit=1, wait_seconds=0.2)

        async def call(path):
            scope = {"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b""}
            sent = []

            async def receive():
                return {"type": "http.request", "body": b"", "more_body": False}

            async def send(message):
                sent.append(message)

            await gate(scope, receive, send)
            return sent

        first = asyncio.create_task(call("/api/v1/subjects"))
        await asyncio.sleep(0.05)
        second = await call("/api/v1/subjects")  # the only slot is taken: 503 after 0.2 s
        health = await call("/health")  # never gated
        release.set()
        return await first, second, health

    first, second, health = asyncio.run(scenario())
    assert first[0]["status"] == 200
    assert second[0]["status"] == 503
    assert (b"retry-after", b"2") in second[0]["headers"]
    assert b"service_busy" in second[1]["body"]
    assert health[0]["status"] == 200


def test_pool_exhaustion_is_a_503(client, catalog, monkeypatch):
    headers = login(client, "demo.student")

    def exhausted(*args, **kwargs):
        raise SATimeoutError("QueuePool limit of size 10 overflow 20 reached", None, None)

    monkeypatch.setattr(catalog_router, "visible_subjects", exhausted)
    response = client.get("/api/v1/subjects", headers=headers)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "service_busy"
    assert response.headers["Retry-After"] == "2"


@pytest.mark.parametrize("value", [True, "123", "1e3", [1]])
def test_progress_rejects_non_numeric_json(client, catalog, value):
    headers = login(client, "demo.student")
    response = client.put(
        f"/api/v1/videos/{catalog.lesson1.id}/progress", json={"position_seconds": value}, headers=headers
    )
    assert response.status_code == 422


def test_progress_accepts_integers_and_floats(client, catalog):
    headers = login(client, "demo.student")
    url = f"/api/v1/videos/{catalog.lesson1.id}/progress"
    assert client.put(url, json={"position_seconds": 12}, headers=headers).json()["position_seconds"] == 12
    assert client.put(url, json={"position_seconds": 12.9}, headers=headers).json()["position_seconds"] == 12


def test_playback_rejects_a_malformed_host_header(client, catalog):
    headers = login(client, "demo.student")
    response = client.post(
        f"/api/v1/videos/{catalog.lesson1.id}/playback", headers={**headers, "Host": "a@evil.example"}
    )
    assert response.status_code == 400
    assert "172." not in response.text and "8000" not in response.text


def test_playback_url_uses_the_host_the_tablet_used(client, catalog):
    headers = login(client, "demo.student")
    response = client.post(
        f"/api/v1/videos/{catalog.lesson1.id}/playback", headers={**headers, "Host": "lms.campus.lan:8080"}
    )
    assert response.json()["playback_url"].startswith("http://lms.campus.lan:8080/media/")


def test_api_docs_use_vendored_assets(client):
    page = client.get("/docs")
    assert page.status_code == 200
    assert "/docs-assets/swagger-ui-bundle.js" in page.text
    assert "cdn.jsdelivr" not in page.text and "fastapi.tiangolo.com" not in page.text
    assert client.get("/docs-assets/swagger-ui.css").status_code == 200
