import argparse
import json

import pytest
from sqlalchemy import func, select

from app import cli
from app.models import Chapter, SchoolClass, Student, Subject, Video
from app.security import verify_password

from .conftest import write_video


def args(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


@pytest.fixture
def manifest(tmp_path):
    write_video("seedtest/cs/one.mp4")
    write_video("seedtest/cs/slow-start.mp4", faststart=False)
    data = {
        "classes": [
            {
                "name": "Seed Class",
                "subjects": [
                    {
                        "name": "CS",
                        "chapters": [
                            {
                                "title": "Intro",
                                "published": True,
                                "videos": [
                                    {"title": "One", "storage_key": "seedtest/cs/one.mp4", "status": "published"},
                                    {"title": "Slow", "storage_key": "seedtest/cs/slow-start.mp4", "status": "published"},
                                    {"title": "Gone", "storage_key": "seedtest/cs/not-there.mp4", "status": "published"},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "students": [
            {"student_code": "seed-1", "username": "Seed.Student", "full_name": "Seed Student", "class": "Seed Class"},
            {"student_code": "seed-2", "username": "seed.off", "full_name": "Off", "class": "Seed Class", "active": False},
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

    assert db.scalar(select(func.count()).select_from(SchoolClass)) == 1
    assert db.scalar(select(func.count()).select_from(Chapter)) == 1
    videos = {v.storage_key: v for v in db.scalars(select(Video))}
    assert set(videos) == {"seedtest/cs/one.mp4", "seedtest/cs/slow-start.mp4"}
    assert videos["seedtest/cs/one.mp4"].status == "published"
    assert videos["seedtest/cs/one.mp4"].duration_seconds == 600
    assert videos["seedtest/cs/one.mp4"].resolution_height == 720
    # Files with problems are never auto-published.
    assert videos["seedtest/cs/slow-start.mp4"].status == "draft"

    student = db.scalar(select(Student).where(Student.username == "seed.student"))
    assert student.student_code == "SEED-1"
    assert verify_password(student.password_hash, "seed-password-1")
    assert db.scalar(select(Student.is_active).where(Student.username == "seed.off")) is False


def test_add_video_registers_a_draft(db, catalog):
    write_video("class12/cs/new.mp4", duration_seconds=95)
    cli.cmd_add_video(
        db,
        args(chapter="Class 12/Computer Science/Basics", storage_key="class12/cs/new.mp4",
             title="New", description=None, sort=5),
    )
    video = db.scalar(select(Video).where(Video.storage_key == "class12/cs/new.mp4"))
    assert video.status == "draft"
    assert video.duration_seconds == 95


@pytest.mark.parametrize("key", ["../etc/x.mp4", "class12/cs/does-not-exist.mp4"])
def test_add_video_rejects_bad_keys_and_missing_files(db, catalog, key):
    with pytest.raises(cli.CliError):
        cli.cmd_add_video(
            db, args(chapter=str(catalog.basics.id), storage_key=key, title="x", description=None, sort=0)
        )


def test_add_video_rejects_duplicates(db, catalog):
    with pytest.raises(cli.CliError):
        cli.cmd_add_video(
            db,
            args(chapter=str(catalog.basics.id), storage_key="class12/cs/lesson-01.mp4", title="dup",
                 description=None, sort=0),
        )


def test_publish_refuses_files_with_problems_unless_forced(db, catalog):
    write_video("class12/cs/draft.mp4", faststart=False)
    with pytest.raises(cli.CliError):
        cli.cmd_set_video_status(db, args(video=str(catalog.draft.id), command="publish-video", force=False))
    cli.cmd_set_video_status(db, args(video=str(catalog.draft.id), command="publish-video", force=True))
    assert catalog.draft.status == "published"
    write_video("class12/cs/draft.mp4")  # restore for other tests


def test_deactivate_student_revokes_sessions(client, db, catalog):
    from .conftest import login

    headers = login(client, "demo.student")
    cli.cmd_set_student_active(db, args(student="demo.student", command="deactivate-student"))
    db.commit()
    assert client.get("/api/v1/me", headers=headers).status_code == 401


def test_check_media_reports_missing_files(db, catalog, capsys):
    assert cli.cmd_check_media(db, args(update=False)) == 1
    assert "class12/cs/missing.mp4" in capsys.readouterr().out


def test_load_students_create_is_rerunnable_and_delete_is_scoped(db, catalog, monkeypatch, client):
    from .conftest import login

    monkeypatch.setenv("LOAD_PW", "load-test-pass")
    args_create = args(count=3, prefix="load", class_ref="Class 12", password_env="LOAD_PW", password_stdin=False)
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


def test_display_name_rules():
    assert cli._display_name("02-python-functions") == (2, "Python Functions")
    assert cli._display_name("class12") == (None, "Class 12")
    assert cli._display_name("computer-science") == (None, "Computer Science")
    assert cli._display_name("01_Intro.to_Algebra") == (1, "Intro.to Algebra")
    assert cli._display_name("lesson-01") == (None, "Lesson 01")


def test_sync_videos_builds_the_catalogue_from_folders(db, catalog, capsys):
    from .conftest import VIDEO_ROOT

    # New lessons dropped on the share; one in a chapter folder, one directly under the subject.
    write_video("class10/general-science/01-matter/02-states-of-matter.mp4", duration_seconds=300)
    write_video("class10/general-science/01-matter/01-what-is-matter.mp4", duration_seconds=240)
    write_video("class10/general-science/quick-revision.mp4", duration_seconds=60)
    write_video("class10/general-science/01-matter/03-not-faststart.mp4", faststart=False)
    (VIDEO_ROOT / "class10" / "title.txt").write_text("Class 10 (Science stream)\n", encoding="utf-8")
    (VIDEO_ROOT / "class10" / "general-science" / "01-matter" / "02-states-of-matter.txt").write_text(
        "States of Matter: solids, liquids, gases\nWith demonstrations.\nSecond paragraph.\n", encoding="utf-8"
    )
    # Things that must be ignored or skipped.
    write_video("loose-file.mp4")
    write_video("class10/general-science/01-matter/too/deep.mp4")

    assert cli.cmd_sync_videos(db, args(publish=True, archive_missing=False)) == 1  # one file with problems
    db.commit()

    school_class = db.scalar(select(SchoolClass).where(SchoolClass.name == "Class 10 (Science stream)"))
    assert school_class is not None
    subject = db.scalar(select(Subject).where(Subject.class_id == school_class.id))
    assert subject.name == "General Science"
    chapters = {c.title: c for c in db.scalars(select(Chapter).where(Chapter.subject_id == subject.id))}
    assert set(chapters) == {"Matter", "Lessons"}
    assert chapters["Matter"].sort_order == 1 and chapters["Matter"].is_published
    videos = {v.storage_key: v for v in db.scalars(select(Video).where(Video.storage_key.like("class10/%")))}
    assert len(videos) == 4
    states = videos["class10/general-science/01-matter/02-states-of-matter.mp4"]
    assert states.title == "States of Matter: solids, liquids, gases"
    assert states.description == "With demonstrations.\nSecond paragraph."
    assert states.sort_order == 2 and states.status == "published" and states.duration_seconds == 300
    assert videos["class10/general-science/01-matter/01-what-is-matter.mp4"].title == "What Is Matter"
    assert videos["class10/general-science/quick-revision.mp4"].chapter_id == chapters["Lessons"].id
    assert videos["class10/general-science/01-matter/03-not-faststart.mp4"].status == "draft"  # problems: never auto-published
    out = capsys.readouterr().out
    assert "skip  loose-file.mp4" in out and "skip  class10/general-science/01-matter/too/deep.mp4" in out
    # The demo videos registered by the fixture are left exactly as they were.
    assert catalog.draft.status == "draft" and catalog.lesson1.status == "published"

    # Re-running changes nothing.
    assert cli.cmd_sync_videos(db, args(publish=True, archive_missing=False)) == 0
    db.commit()
    assert db.scalar(select(func.count()).select_from(Video).where(Video.storage_key.like("class10/%"))) == 4
    assert db.scalar(select(func.count()).select_from(Chapter).where(Chapter.subject_id == subject.id)) == 2

    # A file removed from the share is archived only when asked.
    (VIDEO_ROOT / "class10" / "general-science" / "quick-revision.mp4").unlink()
    cli.cmd_sync_videos(db, args(publish=True, archive_missing=False))
    db.commit()
    assert videos["class10/general-science/quick-revision.mp4"].status == "published"
    cli.cmd_sync_videos(db, args(publish=True, archive_missing=True))
    db.commit()
    assert db.get(Video, videos["class10/general-science/quick-revision.mp4"].id).status == "archived"


def test_lookup_by_path(db, catalog):
    assert cli.find_chapter(db, "Class 12/Computer Science/Basics").id == catalog.basics.id
    with pytest.raises(cli.CliError):
        cli.find_chapter(db, "Class 12/Nope/Basics")
