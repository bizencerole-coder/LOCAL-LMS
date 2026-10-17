import argparse
import json

import pytest
from sqlalchemy import func, select

from app import cli
from app.models import Batch, Content, Module, SchoolClass, StaffUser, Student, Subject
from app.security import verify_password

from .conftest import BATCH, write_pdf, write_video


def args(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


@pytest.fixture
def manifest(tmp_path):
    base = "seedbatch/seedclass/cs/01-intro"
    write_video(f"{base}/one.mp4")
    write_video(f"{base}/slow-start.mp4", faststart=False)
    write_pdf(f"{base}/notes.pdf")
    data = {
        "batches": [
            {
                "name": "Seed Batch",
                "folder": "seedbatch",
                "classes": [
                    {
                        "name": "Seed Class",
                        "folder": "seedclass",
                        "subjects": [
                            {
                                "name": "CS",
                                "folder": "cs",
                                "modules": [
                                    {
                                        "title": "Intro",
                                        "folder": "01-intro",
                                        "published": True,
                                        "contents": [
                                            {"title": "One", "file": "one.mp4", "status": "published"},
                                            {"title": "Slow", "file": "slow-start.mp4", "status": "published"},
                                            {"title": "Notes", "file": "notes.pdf", "status": "published"},
                                            {"title": "Gone", "file": "not-there.mp4", "status": "published"},
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "students": [
            {"student_code": "seed-1", "username": "Seed.Student", "full_name": "Seed Student",
             "class": "Seed Batch/Seed Class"},
            {"student_code": "seed-2", "username": "seed.off", "full_name": "Off", "class": "Seed Batch/Seed Class",
             "active": False},
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(data))
    return path


def test_seed_demo_is_idempotent(db, manifest, monkeypatch):
    monkeypatch.setenv("SEED_PW", "seed-password-1")
    for _ in range(2):
        cli.cmd_seed_demo(db, args(manifest=str(manifest), password_env="SEED_PW", password_stdin=False))
        db.flush()

    assert db.scalar(select(func.count()).select_from(Batch)) == 1
    assert db.scalar(select(func.count()).select_from(SchoolClass)) == 1
    assert db.scalar(select(func.count()).select_from(Module)) == 1
    items = {c.storage_key.rsplit("/", 1)[1]: c for c in db.scalars(select(Content))}
    assert set(items) == {"one.mp4", "slow-start.mp4", "notes.pdf"}
    assert items["one.mp4"].status == "published"
    assert items["one.mp4"].duration_seconds == 600 and items["one.mp4"].resolution_height == 720
    assert items["one.mp4"].storage_key == "seedbatch/seedclass/cs/01-intro/one.mp4"
    assert (items["notes.pdf"].content_type, items["notes.pdf"].mime_type) == ("pdf", "application/pdf")
    assert items["notes.pdf"].checksum and items["notes.pdf"].status == "published"
    # Files with problems are never auto-published.
    assert items["slow-start.mp4"].status == "draft"

    student = db.scalar(select(Student).where(Student.username == "seed.student"))
    assert student.student_code == "SEED-1"
    assert verify_password(student.password_hash, "seed-password-1")
    assert db.get(SchoolClass, student.class_id).name == "Seed Class"
    assert db.scalar(select(Student.is_active).where(Student.username == "seed.off")) is False


def test_structure_commands_create_folders_names(db, catalog):
    cli.cmd_create_batch(db, args(name="NEET 2027", folder=None, description=None))
    batch = db.scalar(select(Batch).where(Batch.name == "NEET 2027"))
    assert batch.folder == "neet-2027"
    cli.cmd_create_class(db, args(batch="NEET 2027", name="Class 12 – Bio", folder=None, description=None))
    school_class = db.scalar(select(SchoolClass).where(SchoolClass.batch_id == batch.id))
    assert school_class.folder == "class-12-bio"
    cli.cmd_create_subject(db, args(class_ref="NEET 2027/Class 12 – Bio", name="Biology", folder="bio", sort=1))
    cli.cmd_create_module(
        db, args(subject="NEET 2027/Class 12 – Bio/Biology", title="Cells", folder=None, description=None, sort=2,
                 publish=True),
    )
    module = db.scalar(select(Module).where(Module.title == "Cells"))
    assert module.folder == "02-cells" and module.is_published
    with pytest.raises(cli.CliError):
        cli.cmd_create_batch(db, args(name="Bad", folder="../up", description=None))


def test_find_class_needs_the_batch_when_names_repeat(db, catalog):
    # "Class 12" exists in this year's batch and in last year's.
    with pytest.raises(cli.CliError, match="Batch 2026-27/Class 12"):
        cli.find_class(db, "Class 12")
    assert cli.find_class(db, "Batch 2026-27/Class 12").id == catalog.class12.id
    assert cli.find_class(db, f"{BATCH}/class12").id == catalog.class12.id  # folders work too
    assert cli.find_class(db, "Class 11").id == catalog.class11.id  # unique name
    assert cli.find_module(db, "Batch 2026-27/Class 12/Computer Science/Basics").id == catalog.basics.id
    with pytest.raises(cli.CliError):
        cli.find_module(db, "Batch 2026-27/Class 12/Nope/Basics")


def test_add_content_registers_drafts_of_any_type(db, catalog):
    key = f"{BATCH}/class12/cs/01-basics/new.mp4"
    write_video(key, duration_seconds=95)
    cli.cmd_add_content(
        db,
        args(module="Batch 2026-27/Class 12/Computer Science/Basics", storage_key=key, title="New",
             description=None, sort=5),
    )
    video = db.scalar(select(Content).where(Content.storage_key == key))
    assert (video.status, video.duration_seconds, video.content_type) == ("draft", 95, "video")

    pdf_key = f"{BATCH}/class12/cs/01-basics/extra.pdf"
    write_pdf(pdf_key)
    cli.cmd_add_content(
        db, args(module=str(catalog.basics.id), storage_key=pdf_key, title="Extra", description=None, sort=6)
    )
    assert db.scalar(select(Content.content_type).where(Content.storage_key == pdf_key)) == "pdf"


@pytest.mark.parametrize("key", ["../etc/x.mp4", f"{BATCH}/class12/cs/does-not-exist.mp4", f"{BATCH}/x/notes.txt"])
def test_add_content_rejects_bad_keys_and_missing_files(db, catalog, key):
    with pytest.raises(cli.CliError):
        cli.cmd_add_content(
            db, args(module=str(catalog.basics.id), storage_key=key, title="x", description=None, sort=0)
        )


def test_add_content_rejects_duplicates(db, catalog):
    with pytest.raises(cli.CliError):
        cli.cmd_add_content(
            db,
            args(module=str(catalog.basics.id), storage_key=catalog.lesson1.storage_key, title="dup",
                 description=None, sort=0),
        )


def test_publish_refuses_files_with_problems_unless_forced(db, catalog):
    write_video(catalog.draft.storage_key, faststart=False)
    with pytest.raises(cli.CliError):
        cli.cmd_set_content_status(db, args(content=str(catalog.draft.id), status_value="published", force=False))
    cli.cmd_set_content_status(db, args(content=str(catalog.draft.id), status_value="published", force=True))
    assert catalog.draft.status == "published"
    write_video(catalog.draft.storage_key)  # restore for other tests


def test_deactivate_student_revokes_sessions(client, db, catalog):
    from .conftest import login

    headers = login(client, "demo.student")
    cli.cmd_set_student_active(db, args(student="demo.student", active_value=False))
    db.commit()
    assert client.get("/api/v1/me", headers=headers).status_code == 401


def test_check_media_reports_missing_files(db, catalog, capsys):
    assert cli.cmd_check_media(db, args(update=False)) == 1
    out = capsys.readouterr().out
    assert "02-advanced/missing.mp4" in out and "notes.pdf" in out


def test_load_students_create_is_rerunnable_and_delete_is_scoped(db, catalog, monkeypatch, client):
    from .conftest import login

    monkeypatch.setenv("LOAD_PW", "load-test-pass")
    args_create = args(count=3, prefix="load", class_ref="Batch 2026-27/Class 12", password_env="LOAD_PW",
                       password_stdin=False)
    cli.cmd_create_load_students(db, args_create)
    cli.cmd_create_load_students(db, args_create)  # second run adds nothing
    db.commit()
    names = sorted(db.scalars(select(Student.username).where(Student.username.like("load%"))))
    assert names == ["load001", "load002", "load003"]
    assert login(client, "load002", "load-test-pass")

    # A real student whose name happens to start with the prefix is not touched.
    db.add(Student(student_code="S12-777", username="loadstone", full_name="Real Student",
                   password_hash="x", class_id=catalog.class12.id))
    db.commit()
    cli.cmd_delete_load_students(db, args(prefix="load"))
    db.commit()
    remaining = sorted(db.scalars(select(Student.username).where(Student.username.like("load%"))))
    assert remaining == ["loadstone"]


def test_staff_accounts(db, monkeypatch, capsys):
    monkeypatch.setenv("STAFF_PW", "staff-password-1")
    cli.cmd_create_staff(
        db, args(username="Principal", name="The Principal", role="admin", password_env="STAFF_PW", password_stdin=False)
    )
    staff = db.scalar(select(StaffUser).where(StaffUser.username == "principal"))
    assert staff.is_admin and verify_password(staff.password_hash, "staff-password-1")
    with pytest.raises(cli.CliError, match="already exists"):
        cli.cmd_create_staff(
            db, args(username="principal", name="x", role="staff", password_env="STAFF_PW", password_stdin=False)
        )
    monkeypatch.setenv("SHORT_PW", "short")
    with pytest.raises(cli.CliError, match="at least 8"):
        cli.cmd_create_staff(
            db, args(username="teacher", name="T", role="staff", password_env="SHORT_PW", password_stdin=False)
        )
    cli.cmd_set_staff_active(db, args(staff="principal", active_value=False))
    assert staff.is_active is False


def test_relocate_moves_pre_batch_folders(db, tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(cli, "get_settings", lambda: SimpleNamespace(video_root=tmp_path))
    batch = Batch(name="Batch 2026-27", folder=BATCH)
    db.add(batch)
    db.flush()
    school_class = SchoolClass(batch_id=batch.id, name="Class 12", folder="class12")
    db.add(school_class)
    db.flush()
    subject = Subject(class_id=school_class.id, name="CS", folder="cs")
    db.add(subject)
    db.flush()
    module = Module(subject_id=subject.id, title="Basics", folder="01-basics", is_published=True)
    db.add(module)
    db.flush()
    db.add(Content(module_id=module.id, title="One", storage_key=f"{BATCH}/class12/cs/01-basics/one.mp4"))
    db.flush()
    # The files are still where the old layout kept them.
    write_video("class12/cs/01-basics/one.mp4", root=tmp_path)
    (tmp_path / "class12" / "cs" / "01-basics" / "one.txt").write_text("One\n")

    cli.cmd_relocate_content(db, args(apply=False, quiet=False))
    assert (tmp_path / "class12").exists()
    cli.cmd_relocate_content(db, args(apply=True, quiet=False))
    assert (tmp_path / BATCH / "class12" / "cs" / "01-basics" / "one.mp4").is_file()
    assert (tmp_path / BATCH / "class12" / "cs" / "01-basics" / "one.txt").is_file()
    assert not (tmp_path / "class12").exists()
    assert cli.relocate_legacy_layout(db, tmp_path, apply=True) == []  # idempotent
