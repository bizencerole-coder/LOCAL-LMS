"""Minimal MP4 inspector (standard library only).

Reads the ``moov`` box to report duration, resolution, codecs and whether the
file is "fast start" (``moov`` before ``mdat``), which progressive playback
needs for a quick start. Used by the admin CLI and ``deploy/scripts/inspect_media.py``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

# Refuse to load absurdly large metadata boxes into memory.
_MAX_MOOV_BYTES = 256 * 1024 * 1024
_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl"}

H264_CODECS = {"avc1", "avc3"}
AAC_CODECS = {"mp4a"}


class Mp4Error(ValueError):
    pass


@dataclass
class TrackInfo:
    handler: str | None = None  # "vide" or "soun"
    codec: str | None = None  # e.g. "avc1", "mp4a"
    width: int | None = None
    height: int | None = None


@dataclass
class Mp4Info:
    size_bytes: int
    duration_seconds: float | None
    faststart: bool
    brands: list[str] = field(default_factory=list)
    tracks: list[TrackInfo] = field(default_factory=list)

    @property
    def video_track(self) -> TrackInfo | None:
        return next((t for t in self.tracks if t.handler == "vide"), None)

    @property
    def audio_track(self) -> TrackInfo | None:
        return next((t for t in self.tracks if t.handler == "soun"), None)

    @property
    def width(self) -> int | None:
        return self.video_track.width if self.video_track else None

    @property
    def height(self) -> int | None:
        return self.video_track.height if self.video_track else None

    @property
    def bitrate_kbps(self) -> float | None:
        if not self.duration_seconds:
            return None
        return self.size_bytes * 8 / self.duration_seconds / 1000

    def problems(self) -> list[str]:
        """Reasons the file does not match the prototype's playback profile."""
        issues: list[str] = []
        video, audio = self.video_track, self.audio_track
        if video is None:
            issues.append("no video track")
        elif video.codec not in H264_CODECS:
            issues.append(f"video codec is {video.codec or 'unknown'}, expected H.264 (avc1)")
        if audio is not None and audio.codec not in AAC_CODECS:
            issues.append(f"audio codec is {audio.codec or 'unknown'}, expected AAC (mp4a)")
        if not self.faststart:
            issues.append("not fast-start (moov after mdat); re-mux with -movflags +faststart")
        if not self.duration_seconds:
            issues.append("duration unknown")
        return issues


def _iter_boxes(f: BinaryIO, start: int, end: int):
    """Yield (type, payload_offset, payload_size) for boxes in [start, end)."""
    offset = start
    while offset + 8 <= end:
        f.seek(offset)
        header = f.read(8)
        if len(header) < 8:
            return
        size, box_type = struct.unpack(">I4s", header)
        header_len = 8
        if size == 1:
            ext = f.read(8)
            if len(ext) < 8:
                return
            (size,) = struct.unpack(">Q", ext)
            header_len = 16
        elif size == 0:
            size = end - offset
        if size < header_len or offset + size > end:
            raise Mp4Error(f"corrupt box {box_type!r} at offset {offset}")
        yield box_type, offset + header_len, size - header_len
        offset += size


def _parse_mvhd(data: bytes) -> float | None:
    version = data[0]
    if version == 1:
        timescale, duration = struct.unpack(">IQ", data[20:32])
    else:
        timescale, duration = struct.unpack(">II", data[12:20])
    if not timescale:
        return None
    return duration / timescale


def _parse_tkhd(data: bytes, track: TrackInfo) -> None:
    base = 4 + (32 if data[0] == 1 else 20)
    # skip reserved(8) layer(2) alt_group(2) volume(2) reserved(2) matrix(36)
    offset = base + 52
    if len(data) >= offset + 8:
        width, height = struct.unpack(">II", data[offset : offset + 8])
        track.width, track.height = width >> 16, height >> 16


def _walk(
    data: bytes, start: int, end: int, info: Mp4Info, track: TrackInfo | None, parent: bytes = b""
) -> None:
    offset = start
    while offset + 8 <= end:
        size, box_type = struct.unpack(">I4s", data[offset : offset + 8])
        header_len = 8
        if size == 1:
            (size,) = struct.unpack(">Q", data[offset + 8 : offset + 16])
            header_len = 16
        elif size == 0:
            size = end - offset
        if size < header_len or offset + size > end:
            raise Mp4Error(f"corrupt box {box_type!r} inside moov")
        payload = data[offset + header_len : offset + size]

        if box_type == b"mvhd":
            info.duration_seconds = _parse_mvhd(payload)
        elif box_type == b"trak":
            new_track = TrackInfo()
            info.tracks.append(new_track)
            _walk(data, offset + header_len, offset + size, info, new_track, box_type)
        elif box_type in _CONTAINERS:
            _walk(data, offset + header_len, offset + size, info, track, box_type)
        elif track is not None and box_type == b"tkhd":
            _parse_tkhd(payload, track)
        elif track is not None and box_type == b"hdlr" and parent == b"mdia" and len(payload) >= 12:
            # Only the media handler; QuickTime files also have a data handler in minf.
            track.handler = payload[8:12].decode("latin-1")
        elif track is not None and box_type == b"stsd" and len(payload) >= 16:
            track.codec = payload[12:16].decode("latin-1")
        offset += size


def inspect_mp4(path: str | Path) -> Mp4Info:
    path = Path(path)
    file_size = path.stat().st_size
    info = Mp4Info(size_bytes=file_size, duration_seconds=None, faststart=False)
    seen_mdat = False
    moov: bytes | None = None

    with path.open("rb") as f:
        for box_type, payload_offset, payload_size in _iter_boxes(f, 0, file_size):
            if box_type == b"ftyp":
                f.seek(payload_offset)
                payload = f.read(min(payload_size, 256))
                brands = [payload[0:4]] + [payload[i : i + 4] for i in range(8, len(payload) - 3, 4)]
                info.brands = [b.decode("latin-1") for b in brands if b.strip(b"\x00")]
            elif box_type == b"mdat":
                seen_mdat = True
            elif box_type == b"moov":
                if payload_size > _MAX_MOOV_BYTES:
                    raise Mp4Error("moov box too large")
                f.seek(payload_offset)
                moov = f.read(payload_size)
                info.faststart = not seen_mdat

    if moov is None:
        raise Mp4Error("not an MP4 file (no moov box found)")
    try:
        _walk(moov, 0, len(moov), info, None)
    except (struct.error, IndexError) as exc:
        raise Mp4Error(f"corrupt metadata inside moov ({exc})") from exc
    return info


def report(paths: list[str | Path]) -> int:
    """Print metadata and profile problems for each file; 1 if any has problems."""
    bad = 0
    for raw in paths:
        try:
            info = inspect_mp4(raw)
        except (Mp4Error, OSError) as exc:
            bad += 1
            print(f"FAIL  {raw}: {exc}")
            continue
        video, audio = info.video_track, info.audio_track
        problems = info.problems()
        minutes, seconds = divmod(round(info.duration_seconds or 0), 60)
        bitrate = f"{info.bitrate_kbps:.0f} kbps" if info.bitrate_kbps else "? kbps"
        print(
            f"{'WARN' if problems else 'OK':<5} {raw}\n"
            f"      {minutes}:{seconds:02d}  {info.width}x{info.height}  "
            f"video {video.codec if video else '-'}  audio {audio.codec if audio else '-'}  "
            f"{bitrate} avg  faststart {'yes' if info.faststart else 'NO'}  {info.size_bytes / 1e6:.1f} MB"
        )
        for problem in problems:
            print(f"      - {problem}")
        bad += bool(problems)
    print(f"{len(paths)} file(s), {bad} with problems")
    return 1 if bad else 0
