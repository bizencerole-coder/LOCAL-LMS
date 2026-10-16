"""Builds tiny synthetic MP4 files (box structure only, no real media)."""

from __future__ import annotations

import struct


def box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), box_type) + payload


def full_box(box_type: bytes, version: int, payload: bytes) -> bytes:
    return box(box_type, bytes([version, 0, 0, 0]) + payload)


def _tkhd(width: int, height: int) -> bytes:
    payload = struct.pack(">IIIII", 0, 0, 1, 0, 0)  # creation, modification, track_id, reserved, duration
    payload += b"\x00" * 8 + struct.pack(">hhhh", 0, 0, 0, 0) + b"\x00" * 36
    payload += struct.pack(">II", width << 16, height << 16)
    return full_box(b"tkhd", 0, payload)


def _track(handler: bytes, codec: bytes, width: int = 0, height: int = 0) -> bytes:
    hdlr = full_box(b"hdlr", 0, struct.pack(">I4s", 0, handler) + b"\x00" * 12 + b"\x00")
    entry = box(codec, b"\x00" * 8)
    stsd = full_box(b"stsd", 0, struct.pack(">I", 1) + entry)
    stbl = box(b"stbl", stsd)
    minf = box(b"minf", stbl)
    mdia = box(b"mdia", hdlr + minf)
    return box(b"trak", _tkhd(width, height) + mdia)


def build_mp4(
    duration_seconds: float = 600,
    width: int = 1280,
    height: int = 720,
    video_codec: bytes = b"avc1",
    audio_codec: bytes | None = b"mp4a",
    faststart: bool = True,
    mvhd_version: int = 0,
    mdat_bytes: int = 1024,
) -> bytes:
    timescale = 1000
    duration = int(duration_seconds * timescale)
    if mvhd_version == 1:
        mvhd_payload = struct.pack(">QQIQ", 0, 0, timescale, duration)
    else:
        mvhd_payload = struct.pack(">IIII", 0, 0, timescale, duration)
    mvhd = full_box(b"mvhd", mvhd_version, mvhd_payload + b"\x00" * 80)
    tracks = _track(b"vide", video_codec, width, height)
    if audio_codec:
        tracks += _track(b"soun", audio_codec)
    moov = box(b"moov", mvhd + tracks)
    ftyp = box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2avc1mp41")
    mdat = box(b"mdat", b"\x00" * mdat_bytes)
    return ftyp + (moov + mdat if faststart else mdat + moov)
