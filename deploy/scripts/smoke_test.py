#!/usr/bin/env python3
"""End-to-end check of a running Campus LMS stack (standard library only).

Exercises the real path a tablet uses: Nginx -> API -> PostgreSQL for login,
catalogue, playback authorization and progress; then Nginx -> disk for signed
MP4 delivery with HTTP Range. Covers AC-01..03, AC-07..09 and T-11, T-18, T-20.

    python3 deploy/scripts/smoke_test.py --base-url http://192.168.10.10
    python3 deploy/scripts/smoke_test.py --base-url http://localhost:8080 \\
        --username demo.student --other-class-username demo.class11

The password is read from LMS_SMOKE_PASSWORD or prompted for.
"""

from __future__ import annotations

import argparse
import getpass
import http.client
import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

RESULTS: list[tuple[bool, str, str]] = []


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - urllib API
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def request(method, url, *, token=None, body=None, headers=None, read_limit=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    started = time.perf_counter()
    try:
        try:
            resp = OPENER.open(req, timeout=15)
        except urllib.error.HTTPError as err:
            resp = err
        payload = resp.read(read_limit) if read_limit else resp.read()
    except (urllib.error.URLError, OSError, http.client.HTTPException) as err:
        # Unreachable, refused, timed out or cut off: report status 0 and keep going.
        elapsed = (time.perf_counter() - started) * 1000
        return 0, {"X-Smoke-Error": str(getattr(err, "reason", err))}, b"", elapsed
    elapsed = (time.perf_counter() - started) * 1000
    return resp.status, dict(resp.headers.items()), payload, elapsed


def check(ok: bool, name: str, detail: str = "") -> bool:
    RESULTS.append((ok, name, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{('  -- ' + detail) if detail else ''}")
    return ok


def json_body(payload: bytes):
    try:
        return json.loads(payload or b"null")
    except json.JSONDecodeError:
        return None


def login(base, username, password):
    status, _, payload, ms = request(
        "POST", f"{base}/api/v1/auth/login", body={"username": username, "password": password}
    )
    body = json_body(payload) or {}
    return status, body.get("access_token"), ms


def first_video(base, token):
    status, _, payload, _ = request("GET", f"{base}/api/v1/subjects", token=token)
    subjects = json_body(payload) if status == 200 else None
    check(status == 200 and isinstance(subjects, list) and subjects, "list subjects", f"status {status}")
    for subject in subjects or []:
        _, _, payload, _ = request("GET", f"{base}/api/v1/subjects/{subject['id']}/chapters", token=token)
        for chapter in json_body(payload) or []:
            _, _, payload, _ = request("GET", f"{base}/api/v1/chapters/{chapter['id']}/videos", token=token)
            videos = json_body(payload) or []
            if videos:
                return subject, chapter, videos[0]
    return None, None, None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--username", default="demo.student")
    parser.add_argument("--other-class-username", help="student of another class, to test access control")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")
    password = os.environ.get("LMS_SMOKE_PASSWORD") or getpass.getpass(f"Password for {args.username}: ")

    print(f"Campus LMS smoke test against {base}\n")

    # --- Services ---------------------------------------------------------------
    status, headers, _, _ = request("GET", f"{base}/nginx-health")
    if not check(status == 200, "nginx is up", f"status {status} {headers.get('X-Smoke-Error', '')}".strip()):
        return summary()
    status, _, _, _ = request("GET", f"{base}/health")
    check(status == 200, "API /health", f"status {status}")
    status, _, payload, _ = request("GET", f"{base}/ready")
    check(status == 200, "API /ready (database + media storage)", payload.decode(errors="replace").strip())

    # --- Authentication ---------------------------------------------------------
    status, _, _ = login(base, args.username, password + "-wrong")
    check(status == 401, "wrong password rejected", f"status {status}")
    status, token, ms = login(base, args.username, password)
    if not check(status == 200 and token, "login", f"status {status}, {ms:.0f} ms"):
        return summary()
    status, _, payload, _ = request("GET", f"{base}/api/v1/me", token=token)
    me = json_body(payload) or {}
    check(status == 200, "GET /me", f"{me.get('full_name')} / {(me.get('class') or {}).get('name')}")

    # --- Catalogue and playback authorization -----------------------------------
    subject, chapter, video = first_video(base, token)
    if not check(video is not None, "found a published lesson", video["title"] if video else "none"):
        return summary()
    status, _, payload, ms = request("POST", f"{base}/api/v1/videos/{video['id']}/playback", token=token)
    playback = json_body(payload) or {}
    url = playback.get("playback_url", "")
    if not check(status == 200 and url, "playback authorized", f"{ms:.0f} ms"):
        return summary()
    host = urlsplit(url).hostname or ""
    check(not host.endswith((".com", ".net", ".org", ".io")), "playback URL is local", host)

    # --- Video delivery (AC-03, AC-08) ------------------------------------------
    status, headers, _, ms = request("HEAD", url)
    size = int(headers.get("Content-Length", "0"))
    check(status == 200, "HEAD signed URL", f"{size / 1e6:.1f} MB, {ms:.0f} ms")
    check(headers.get("Content-Type", "").startswith("video/mp4"), "Content-Type is video/mp4", headers.get("Content-Type", ""))
    check(headers.get("Accept-Ranges") == "bytes", "Accept-Ranges: bytes", headers.get("Accept-Ranges", "missing"))

    for label, range_header, expected_start in (
        ("start", "bytes=0-1023", 0),
        ("middle", f"bytes={size // 2}-{size // 2 + 1023}", size // 2),
        ("near end", "bytes=-1024", max(size - 1024, 0)),
    ):
        status, headers, payload, ms = request("GET", url, headers={"Range": range_header}, read_limit=2048)
        content_range = headers.get("Content-Range", "")
        ok = status == 206 and content_range.startswith(f"bytes {expected_start}-") and len(payload) == 1024
        check(ok, f"range request ({label})", f"{status} {content_range}, first byte in {ms:.0f} ms")

    # --- Media access control (FR-04, T-20) -------------------------------------
    parts = urlsplit(url)
    unsigned = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    status, _, _, _ = request("HEAD", unsigned)
    check(status == 403, "unsigned media URL denied", f"status {status}")
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    # Change the first character to one it is not (changing the last one may decode to
    # the same digest, since base64 pads the final bits).
    tampered = dict(query, md5=("B" if query["md5"][0] == "A" else "A") + query["md5"][1:])
    assert tampered["md5"] != query["md5"]
    status, _, _, _ = request("HEAD", urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(tampered), "")))
    check(status == 403, "tampered signature denied", f"status {status}")
    moved = dict(query, expires=str(int(query["expires"]) + 86400))
    status, _, _, _ = request("HEAD", urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(moved), "")))
    check(status == 403, "extended expiry denied", f"status {status}")
    status, _, _, _ = request("POST", url)
    check(status == 405, "non-GET method on media denied", f"status {status}")
    for path in ("/media/", parts.path.rsplit("/", 1)[0] + "/", "/"):
        status, _, payload, _ = request("GET", f"{base}{path}")
        check(status in (403, 404) and b"Index of" not in payload, f"no directory listing at {path}", f"status {status}")
    status, _, _, _ = request("GET", f"{base}/media/../etc/passwd")
    check(status in (400, 403, 404), "path traversal blocked", f"status {status}")

    # --- Progress (AC-09, T-18) -------------------------------------------------
    for position in (41, 42):
        status, _, _, _ = request(
            "PUT", f"{base}/api/v1/videos/{video['id']}/progress", token=token,
            body={"position_seconds": position, "duration_seconds": playback.get("duration_seconds")},
        )
    check(status == 200, "save progress", f"status {status}")
    status, _, payload, _ = request("GET", f"{base}/api/v1/videos/{video['id']}/progress", token=token)
    check((json_body(payload) or {}).get("position_seconds") == 42, "read progress back", payload.decode(errors="replace"))

    # --- Another class cannot get this lesson (AC-07, T-11) ---------------------
    if args.other_class_username:
        status, other_token, _ = login(base, args.other_class_username, password)
        if check(status == 200, f"login as {args.other_class_username}", f"status {status}"):
            status, _, _, _ = request("POST", f"{base}/api/v1/videos/{video['id']}/playback", token=other_token)
            check(status == 404, "other class denied playback", f"status {status}")
            request("POST", f"{base}/api/v1/auth/logout", token=other_token)

    # --- Sign-out ---------------------------------------------------------------
    request("POST", f"{base}/api/v1/auth/logout", token=token)
    status, _, _, _ = request("GET", f"{base}/api/v1/me", token=token)
    check(status == 401, "token invalid after logout", f"status {status}")
    return summary()


def summary() -> int:
    failed = [name for ok, name, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    for name in failed:
        print(f"  failed: {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
