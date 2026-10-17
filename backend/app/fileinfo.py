"""Checks and metadata for content files (videos, PDF notes, images).

Pure file inspection: no database access. Used by the folder sync, the dashboard
upload and the admin CLI.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass, field
from pathlib import Path

from .media import content_type_for
from .models import ContentType
from .mp4info import Mp4Error, inspect_mp4


class ContentFileError(ValueError):
    """The file is missing, unreadable, or not what its extension says."""


@dataclass
class ContentFileInfo:
    content_type: ContentType
    mime_type: str
    size_bytes: int
    duration_seconds: int | None = None
    width: int | None = None
    height: int | None = None
    checksum: str | None = None
    # Warnings: the file is usable, but should be fixed before students see it.
    problems: list[str] = field(default_factory=list)

    def metadata(self) -> dict:
        """Column values for a Content row."""
        return {
            "content_type": self.content_type.value,
            "mime_type": self.mime_type,
            "file_size_bytes": self.size_bytes,
            "duration_seconds": self.duration_seconds,
            "resolution_width": self.width,
            "resolution_height": self.height,
            "checksum": self.checksum,
        }


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def inspect_content_file(path: Path, *, checksum: str | None = None, compute_checksum: bool | None = None) -> ContentFileInfo:
    """Inspect ``path``. ``checksum`` may be passed when already known (uploads).

    By default a checksum is computed for notes and images (small files) and not for
    videos, which are matched by size and duration instead.
    """
    kind = content_type_for(path.name)
    if kind is None:
        raise ContentFileError(f"Unsupported file type: {path.name}")
    content_type, mime = kind
    if not path.is_file():
        raise ContentFileError(f"File not found: {path}")
    if not os.access(path, os.R_OK):
        raise ContentFileError(f"File is not readable: {path}")
    size = path.stat().st_size
    if size == 0:
        raise ContentFileError(f"File is empty: {path.name}")

    info = ContentFileInfo(content_type=content_type, mime_type=mime, size_bytes=size)
    if content_type is ContentType.VIDEO:
        try:
            mp4 = inspect_mp4(path)
        except (Mp4Error, OSError) as exc:
            raise ContentFileError(f"Cannot read {path.name} as an MP4 video: {exc}") from exc
        info.duration_seconds = round(mp4.duration_seconds) if mp4.duration_seconds else None
        info.width, info.height = mp4.width, mp4.height
        info.problems = mp4.problems()
    elif content_type is ContentType.PDF:
        _check_pdf(path)
    else:
        info.width, info.height = _image_size(path, mime)

    if checksum is not None:
        info.checksum = checksum
    elif compute_checksum or (compute_checksum is None and content_type is not ContentType.VIDEO):
        info.checksum = sha256_file(path)
    return info


def _check_pdf(path: Path) -> None:
    with path.open("rb") as handle:
        head = handle.read(1024)
    if b"%PDF-" not in head:
        raise ContentFileError(f"{path.name} is not a PDF file (no %PDF header).")


_IMAGE_SIGNATURES = (
    ("image/png", lambda head: head[:8] == b"\x89PNG\r\n\x1a\n"),
    ("image/jpeg", lambda head: head[:3] == b"\xff\xd8\xff"),
    ("image/webp", lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP"),
)


def sniff_image(data: bytes) -> tuple[str, int | None, int | None] | None:
    """(MIME type, width, height) of PNG, JPEG or WebP ``data`` by its content; else None."""
    head = data[: 64 * 1024]
    for mime, matches in _IMAGE_SIGNATURES:
        if matches(head):
            try:
                width, height = _size_from_head(head, mime)
            except (struct.error, IndexError):
                width = height = None
            return mime, width, height
    return None


def _size_from_head(head: bytes, mime: str) -> tuple[int | None, int | None]:
    if mime == "image/png":
        return struct.unpack(">II", head[16:24])
    if mime == "image/jpeg":
        return _jpeg_size(head)
    return _webp_size(head)


def _image_size(path: Path, mime: str) -> tuple[int | None, int | None]:
    with path.open("rb") as handle:
        head = handle.read(64 * 1024)
    try:
        if mime == "image/png":
            if head[:8] != b"\x89PNG\r\n\x1a\n":
                raise ContentFileError(f"{path.name} is not a PNG image.")
            width, height = struct.unpack(">II", head[16:24])
            return width, height
        if mime == "image/jpeg":
            if head[:3] != b"\xff\xd8\xff":
                raise ContentFileError(f"{path.name} is not a JPEG image.")
            return _jpeg_size(head)
        if mime == "image/webp":
            if head[:4] != b"RIFF" or head[8:12] != b"WEBP":
                raise ContentFileError(f"{path.name} is not a WebP image.")
            return _webp_size(head)
    except (struct.error, IndexError):
        return None, None
    return None, None


def _jpeg_size(data: bytes) -> tuple[int | None, int | None]:
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        # SOF0..SOF15 except DHT (C4), JPG (C8) and DAC (CC) carry the frame size.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return width, height
        i += 2 + length
    return None, None


def _webp_size(data: bytes) -> tuple[int | None, int | None]:
    chunk = data[12:16]
    if chunk == b"VP8 ":
        width, height = struct.unpack("<HH", data[26:30])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X":
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return width, height
    return None, None
