import pytest

from app.mp4info import Mp4Error, inspect_mp4

from .mp4_builder import build_mp4


def write(tmp_path, data, name="v.mp4"):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_reads_duration_resolution_codecs_and_faststart(tmp_path):
    info = inspect_mp4(write(tmp_path, build_mp4(duration_seconds=754.5)))
    assert info.duration_seconds == pytest.approx(754.5)
    assert (info.width, info.height) == (1280, 720)
    assert info.video_track.codec == "avc1"
    assert info.audio_track.codec == "mp4a"
    assert info.faststart is True
    assert "isom" in info.brands
    assert info.problems() == []


def test_version_1_mvhd(tmp_path):
    info = inspect_mp4(write(tmp_path, build_mp4(duration_seconds=7200, mvhd_version=1)))
    assert info.duration_seconds == pytest.approx(7200)


def test_detects_moov_after_mdat(tmp_path):
    info = inspect_mp4(write(tmp_path, build_mp4(faststart=False)))
    assert info.faststart is False
    assert any("fast-start" in p for p in info.problems())


def test_flags_unsupported_codecs(tmp_path):
    info = inspect_mp4(write(tmp_path, build_mp4(video_codec=b"hvc1", audio_codec=b"Opus")))
    problems = " ".join(info.problems())
    assert "H.264" in problems and "AAC" in problems


def test_video_without_audio_is_acceptable(tmp_path):
    assert inspect_mp4(write(tmp_path, build_mp4(audio_codec=None))).problems() == []


def test_rejects_non_mp4(tmp_path):
    with pytest.raises(Mp4Error):
        inspect_mp4(write(tmp_path, b"this is not a video file at all"))


def test_rejects_truncated_box(tmp_path):
    data = build_mp4()
    with pytest.raises(Mp4Error):
        inspect_mp4(write(tmp_path, data[: len(data) - 100]))
