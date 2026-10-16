"""Storage keys and signed playback URLs.

Playback URLs use the Nginx ``secure_link`` module, so Nginx serves video bytes
(with Range support) without calling the API per request. The signature binds
the expiry time, the media URI and the student ID:

    md5 = base64url(md5("{expires}{uri}{sid} {secret}"))   # no padding

which must match ``secure_link_md5`` in ``deploy/nginx/templates/site.conf.template``.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path
from urllib.parse import quote, urlencode

ALLOWED_EXTENSIONS = (".mp4", ".m4v")

# Relative path of lower-risk characters only: no "..", no leading "/", no spaces,
# nothing needing URL encoding (so the signed URI equals Nginx's decoded $uri).
_STORAGE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")
MAX_STORAGE_KEY_LENGTH = 500


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
            "(for example class12/computer-science/lesson-01.mp4)."
        )
    if not key.lower().endswith(ALLOWED_EXTENSIONS):
        raise InvalidStorageKey(f"Only {', '.join(ALLOWED_EXTENSIONS)} files are supported.")
    return key


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
    uri = prefix + validate_storage_key(storage_key)
    signature = sign_media_uri(uri, expires, sid, secret)
    query = urlencode({"expires": expires, "sid": sid, "md5": signature})
    return f"{base_url.rstrip('/')}{quote(uri, safe='/')}?{query}"
