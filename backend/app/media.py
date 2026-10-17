"""Storage keys, file types, folder names and signed media URLs.

Media URLs use the Nginx ``secure_link`` module, so Nginx serves the bytes (with Range
support) without calling the API per request. The signature binds the expiry time,
the media URI and the viewer ID (student ID, or ``staff-<id>`` for dashboard previews):

    md5 = base64url(md5("{expires}{uri}{sid} {secret}"))   # no padding

which must match ``secure_link_md5`` in ``deploy/nginx/templates/site.conf.template``.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import unicodedata
from pathlib import Path
from urllib.parse import quote, urlencode

from .models import ContentType

# Extension -> (content type, MIME type). Nginx serves exactly these types (site.conf.template).
EXTENSION_TYPES: dict[str, tuple[ContentType, str]] = {
    ".mp4": (ContentType.VIDEO, "video/mp4"),
    ".m4v": (ContentType.VIDEO, "video/mp4"),
    ".pdf": (ContentType.PDF, "application/pdf"),
    ".jpg": (ContentType.IMAGE, "image/jpeg"),
    ".jpeg": (ContentType.IMAGE, "image/jpeg"),
    ".png": (ContentType.IMAGE, "image/png"),
    ".webp": (ContentType.IMAGE, "image/webp"),
}
ALLOWED_EXTENSIONS = tuple(EXTENSION_TYPES)

# Relative path of lower-risk characters only: no "..", no leading "/", no spaces,
# nothing needing URL encoding (so the signed URI equals Nginx's decoded $uri). Every
# part starts with a letter or digit, so hidden folders (.uploads, .trash) never match.
_STORAGE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")
_FOLDER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
MAX_STORAGE_KEY_LENGTH = 500
MAX_FOLDER_LENGTH = 100


class InvalidStorageKey(ValueError):
    pass


def validate_storage_key(key: str) -> str:
    key = key.strip().replace("\\", "/")
    if not key or len(key) > MAX_STORAGE_KEY_LENGTH:
        raise InvalidStorageKey("Storage key must be 1-500 characters.")
    if not _STORAGE_KEY_RE.match(key):
        raise InvalidStorageKey(
            "Storage key must be a relative path using only letters, digits, '.', '-', '_' "
            "and '/', with each part starting with a letter or digit "
            "(for example batch-2026-27/class12/computer-science/01-basics/01-intro.mp4)."
        )
    if content_type_for(key) is None:
        raise InvalidStorageKey(f"Only {', '.join(ALLOWED_EXTENSIONS)} files are supported.")
    return key


def content_type_for(name: str) -> tuple[ContentType, str] | None:
    """(content type, MIME type) for a file name, or None if the type is not supported."""
    return EXTENSION_TYPES.get(os.path.splitext(name)[1].lower())


def is_valid_folder(name: str) -> bool:
    return bool(name) and len(name) <= MAX_FOLDER_LENGTH and bool(_FOLDER_RE.match(name))


def slugify(text: str, max_length: int = 60, fallback: str = "item") -> str:
    """'Class 12 – Science!' -> 'class-12-science'. Always a valid folder/file name part."""
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    slug = slug[:max_length].rstrip("-")
    return slug or fallback


def resolve_media_path(video_root: Path, storage_key: str) -> Path:
    key = validate_storage_key(storage_key)
    return video_root.joinpath(*key.split("/"))


def is_readable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.R_OK)


def sign_media_uri(uri: str, expires: int, sid: str, secret: str) -> str:
    raw = f"{expires}{uri}{sid} {secret}".encode()
    return base64.urlsafe_b64encode(hashlib.md5(raw).digest()).rstrip(b"=").decode("ascii")


def build_playback_url(
    *,
    base_url: str,
    prefix: str,
    storage_key: str,
    sid: str,
    expires: int,
    secret: str,
) -> str:
    """Signed media URL. ``base_url`` may be empty for a same-origin relative URL."""
    uri = prefix + validate_storage_key(storage_key)
    signature = sign_media_uri(uri, expires, sid, secret)
    query = urlencode({"expires": expires, "sid": sid, "md5": signature})
    return f"{base_url.rstrip('/')}{quote(uri, safe='/')}?{query}"
