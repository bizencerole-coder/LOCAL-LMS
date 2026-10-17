"""The folder sync (cron, CLI and the dashboard's "Sync now")."""

import pytest
from sqlalchemy import func, select

from app.catalog_sync import display_name, record_sync_run, sync_catalogue
from app.models import Batch, Content, ContentProgress, Module, SchoolClass, Subject, SyncRun

from .conftest import write_pdf, write_png, write_video

B = "batch-2026-27"


@pytest.fixture
def root(tmp_path):
    return tmp_path


@pytest.fixture
def batch(db):
    item = Batch(name="Batch 2026-27", folder=B)
    db.add(item)
    db.commit()
    return item


def sync(db, root, publish=True, archive=False, **kwargs):
    result = sync_catalogue(db, root, publish=publish, archive_missing=archive, **kwargs)
    db.commit()
    return result


def items(db, prefix=""):
    return {c.storage_key: c for c in db.scalars(select(Content).where(Content.storage_key.like(f"{prefix}%")))}


def test_display_name_rules():
    assert display_name("02-python-functions") == (2, "Python Functions")
    assert display_name("class12") == (None, "Class 12")
    assert display_name("computer-science") == (None, "Computer Science")
    assert display_name("01_Intro.to_Algebra") == (1, "Intro.to Algebra")
    assert display_name("lesson-01") == (None, "Lesson 01")


def test_sync_builds_the_catalogue_from_folders(db, batch, root):
    science = f"{B}/class10/general-science"
    write_video(f"{science}/01-matter/02-states-of-matter.mp4", root=root, duration_seconds=300)
    write_video(f"{science}/01-matter/01-what-is-matter.mp4", root=root, duration_seconds=240)
    write_pdf(f"{science}/01-matter/03-matter-notes.pdf", root=root)
    write_png(f"{science}/01-matter/04-particle-diagram.png", root=root, width=40, height=30)
    write_video(f"{science}/quick-revision.mp4", root=root, duration_seconds=60)
    write_video(f"{science}/01-matter/05-not-faststart.mp4", root=root, faststart=False)
    (root / B / "class10" / "title.txt").write_text("Class 10 (Science stream)\n", encoding="utf-8")
    (root / B / "class10" / "general-science" / "01-matter" / "02-states-of-matter.txt").write_text(
        "States of Matter: solids, liquids, gases\nWith demonstrations.\nSecond paragraph.\n", encoding="utf-8"
    )
    # Things that must be ignored or skipped.
    write_video("loose-file.mp4", root=root)
    write_video("class10/physics/motion/speed.mp4", root=root)  # old layout: no batch folder
    write_video(f"{science}/01-matter/too/deep.mp4", root=root)
    write_video(f"{B}/.uploads/partial.mp4", root=root)
    (root / B / "class10" / "general-science" / "01-matter" / "readme.docx").write_bytes(b"x")

    result = sync(db, root)
    assert result.problems == 1  # the non-faststart video
    school_class = db.scalar(select(SchoolClass).where(SchoolClass.folder == "class10"))
    assert school_class.name == "Class 10 (Science stream)" and school_class.batch_id == batch.id
    subject = db.scalar(select(Subject).where(Subject.class_id == school_class.id))
    assert (subject.name, subject.folder) == ("General Science", "general-science")
    modules = {m.title: m for m in db.scalars(select(Module).where(Module.subject_id == subject.id))}
    assert set(modules) == {"Matter", "General"}
    assert modules["Matter"].sort_order == 1 and modules["Matter"].is_published
    assert modules["General"].folder == ""
    found = items(db, B)
    assert len(found) == 6
    states = found[f"{science}/01-matter/02-states-of-matter.mp4"]
    assert states.title == "States of Matter: solids, liquids, gases"
    assert states.description == "With demonstrations.\nSecond paragraph."
    assert states.sort_order == 2 and states.status == "published" and states.duration_seconds == 300
    notes = found[f"{science}/01-matter/03-matter-notes.pdf"]
    assert (notes.content_type, notes.title, notes.checksum is not None) == ("pdf", "Matter Notes", True)
    diagram = found[f"{science}/01-matter/04-particle-diagram.png"]
    assert (diagram.content_type, diagram.resolution_width, diagram.resolution_height) == ("image", 40, 30)
    assert found[f"{science}/quick-revision.mp4"].module_id == modules["General"].id
    assert found[f"{science}/01-matter/05-not-faststart.mp4"].status == "draft"  # problems: never auto-published
    report = result.report
    assert "skip  loose-file.mp4" in report
    assert "skip  class10/...: 1 file(s) in a folder that is not a batch" in report
    assert f"skip  {science}/01-matter/too/deep.mp4" in report
    assert "partial" not in report and "readme" not in report

    # Re-running changes nothing.
    again = sync(db, root)
    assert (again.registered, again.moved, again.updated, again.already) == (0, 0, 0, 6)
    assert db.scalar(select(func.count()).select_from(Module).where(Module.subject_id == subject.id)) == 2

    # A file removed from the share is archived only when asked.
    (root / B / "class10" / "general-science" / "quick-revision.mp4").unlink()
    sync(db, root)
    assert found[f"{science}/quick-revision.mp4"].status == "published"
    sync(db, root, archive=True)
    assert db.get(Content, found[f"{science}/quick-revision.mp4"].id).status == "archived"


def test_sync_follows_moved_renamed_and_replaced_files(db, batch, root, client):
    base = f"{B}/class9/maths"
    write_video(f"{base}/01-algebra/01-linear-equations.mp4", root=root, duration_seconds=300, mdat_bytes=5000)
    write_video(f"{base}/01-algebra/02-quadratics.mp4", root=root, duration_seconds=240, mdat_bytes=7000)
    write_pdf(f"{base}/01-algebra/03-worksheet.pdf", root=root, text="Worksheet")
    algebra = root / B / "class9" / "maths" / "01-algebra"
    (algebra / "02-quadratics.txt").write_text("Quadratic Equations: an introduction\n", encoding="utf-8")
    sync(db, root)
    found = items(db, B)
    linear = found[f"{base}/01-algebra/01-linear-equations.mp4"]
    quadratics = found[f"{base}/01-algebra/02-quadratics.mp4"]
    worksheet = found[f"{base}/01-algebra/03-worksheet.pdf"]
    algebra_module_id = linear.module_id
    from app.models import Student

    student = Student(student_code="S9", username="s9", full_name="S", password_hash="x")
    db.add(student)
    db.flush()
    db.add(ContentProgress(student_id=student.id, content_id=linear.id, position_seconds=120, duration_seconds=300))
    db.commit()

    # The teacher renames the module folder and a file, and moves two items to a new module.
    basics = algebra.parent / "02-algebra-basics"
    algebra.rename(basics)
    (basics / "01-linear-equations.mp4").rename(basics / "01-linear-equations-in-one-variable.mp4")
    polynomials = algebra.parent / "03-polynomials"
    polynomials.mkdir()
    (basics / "02-quadratics.mp4").rename(polynomials / "01-quadratics.mp4")
    (basics / "02-quadratics.txt").unlink()
    (basics / "03-worksheet.pdf").rename(polynomials / "02-practice.pdf")
    result = sync(db, root, archive=True)
    assert (result.moved, result.archived, result.registered) == (3, 0, 0)

    linear = db.get(Content, linear.id)
    assert linear.storage_key == f"{base}/02-algebra-basics/01-linear-equations-in-one-variable.mp4"
    assert linear.title == "Linear Equations In One Variable"  # an automatic name follows the file name
    assert db.get(Module, linear.module_id).title == "Algebra Basics"
    quadratics = db.get(Content, quadratics.id)
    assert quadratics.title == "Quadratic Equations: an introduction"  # a custom title is kept
    assert db.get(Module, quadratics.module_id).title == "Polynomials"
    worksheet = db.get(Content, worksheet.id)  # a PDF is followed by its checksum
    assert worksheet.storage_key == f"{base}/03-polynomials/02-practice.pdf" and worksheet.title == "Practice"
    progress = db.scalar(select(ContentProgress).where(ContentProgress.content_id == linear.id))
    assert progress.position_seconds == 120  # progress travelled with the file
    assert db.get(Module, algebra_module_id) is None  # emptied by the moves, so removed
    assert "1 empty module(s) removed" in result.summary

    # A file replaced in place (re-encoded, or a copy that has finished) gets fresh metadata.
    write_video(f"{base}/03-polynomials/01-quadratics.mp4", root=root, duration_seconds=900, mdat_bytes=9000)
    assert sync(db, root, archive=True).updated == 1
    assert db.get(Content, quadratics.id).duration_seconds == 900


def test_sync_does_not_guess_between_identical_files(db, batch, root):
    base = f"{B}/class9/maths/01-algebra"
    write_video(f"{base}/01-a.mp4", root=root, duration_seconds=300, mdat_bytes=5000)
    for name in ("02-b.mp4", "03-c.mp4", "04-d.mp4", "05-e.mp4", "06-f.mp4"):
        write_video(f"{base}/{name}", root=root, duration_seconds=10, mdat_bytes=10)
    sync(db, root)
    original = items(db)[f"{base}/01-a.mp4"]

    # Two identical copies appear while the original disappears: nothing tells them apart.
    (root / B / "class9" / "maths" / "01-algebra" / "01-a.mp4").unlink()
    write_video(f"{base}/07-b.mp4", root=root, duration_seconds=300, mdat_bytes=5000)
    write_video(f"{base}/08-c.mp4", root=root, duration_seconds=300, mdat_bytes=5000)
    sync(db, root, archive=True)
    assert db.get(Content, original.id).status == "archived"
    assert db.get(Content, original.id).storage_key == f"{base}/01-a.mp4"
    assert len(items(db, B)) == 8


def test_sync_never_archives_an_empty_or_mostly_missing_library(db, batch, root):
    base = f"{B}/class9/maths/01-algebra"
    for n in range(1, 13):
        write_video(f"{base}/{n:02d}-lesson.mp4", root=root, duration_seconds=n, mdat_bytes=n)
    sync(db, root)
    # Most files vanish (a half-copied restore, a wrong mount...): nothing is archived.
    for n in range(1, 10):
        (root / B / "class9" / "maths" / "01-algebra" / f"{n:02d}-lesson.mp4").unlink()
    result = sync(db, root, archive=True)
    assert result.archived == 0 and "nothing archived" in result.report
    assert sync(db, root, archive=True, allow_mass_archive=True).archived == 9

    # The whole folder empty (storage not mounted): never archives.
    for path in root.rglob("*.mp4"):
        path.unlink()
    result = sync(db, root, archive=True, allow_mass_archive=True)
    assert result.archived == 0 and "is the storage mounted" in result.report


def test_sync_runs_are_recorded(db, batch, root):
    write_video(f"{B}/class9/maths/01-algebra/01-a.mp4", root=root)
    result = sync_catalogue(db, root, publish=False, archive_missing=False)
    run = record_sync_run(db, result, trigger="cli")
    db.commit()
    stored = db.get(SyncRun, run.id)
    assert stored.registered == 1 and stored.trigger == "cli"
    assert "registered as draft" in stored.report
    assert items(db)[f"{B}/class9/maths/01-algebra/01-a.mp4"].status == "draft"
