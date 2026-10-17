"""Page rendering for the dashboard: templates, filters, flash messages, redirects."""

from __future__ import annotations

import base64
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ..config import get_settings
from ..models import ContentType, as_utc, utcnow

FLASH_COOKIE = "lms_flash"
TEMPLATES = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")

# Same-origin only; no inline script. Media previews come from /media/ on this host.
CSP = (
    "default-src 'self'; img-src 'self' data:; media-src 'self'; frame-src 'self'; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


PERMISSION_HELP = (
    "The server is not allowed to change files in the content folder, so uploads and folder changes fail. "
    "An administrator must make the API run as the owner of the content folder: in deploy/.env set "
    "LMS_CONTENT_UID and LMS_CONTENT_GID to the folder's owner (stat -c '%u %g' <content folder>), "
    "then run: docker compose up -d api"
)


def unwritable(paths) -> list[str]:
    """Names of the existing folders among ``paths`` this process may not write to."""
    import os

    return [p.name or str(p) for p in paths if p.exists() and not os.access(p, os.W_OK)]


class FormError(Exception):
    """A submitted form could not be applied: go back and show the message."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFound(Exception):
    def __init__(self, what: str = "page") -> None:
        super().__init__(what)
        self.what = what


# --------------------------------------------------------------------------- filters


def _tz():
    try:
        return ZoneInfo(get_settings().display_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return ""
    h, rem = divmod(int(seconds), 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size(size: int | None) -> str:
    if size is None:
        return ""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def fmt_time(value: datetime | None) -> str:
    if value is None:
        return ""
    return as_utc(value).astimezone(_tz()).strftime("%d %b %Y, %H:%M")


def fmt_date(value: datetime | None) -> str:
    if value is None:
        return ""
    return as_utc(value).astimezone(_tz()).strftime("%d %b %Y")


def fmt_until(value: datetime | None) -> str:
    """The last day of an "until" moment stored as the start of the next day."""
    if value is None:
        return ""
    return fmt_date(as_utc(value) - timedelta(microseconds=1))


def date_value(value: datetime | None, end_of_day: bool = False) -> str:
    """``value`` as YYYY-MM-DD in local time, for a date input (see parse_local_date)."""
    if value is None:
        return ""
    local = as_utc(value).astimezone(_tz())
    if end_of_day:
        local -= timedelta(microseconds=1)
    return local.strftime("%Y-%m-%d")


def parse_local_date(value: object, what: str, *, end_of_day: bool = False) -> datetime | None:
    """A YYYY-MM-DD date input as a moment: the start of that local day, or its end
    (the start of the next day) for "until" dates. Empty -> None."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        day = date.fromisoformat(text)
    except ValueError as exc:
        raise FormError(f"{what}: enter a date such as 2026-11-30.") from exc
    if end_of_day:
        day += timedelta(days=1)
    return datetime(day.year, day.month, day.day, tzinfo=_tz()).astimezone(UTC)


def fmt_ago(value: datetime | None) -> str:
    if value is None:
        return "never"
    seconds = int((utcnow() - as_utc(value)).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} h ago"
    if seconds < 7 * 86400:
        return f"{seconds // 86400} d ago"
    return fmt_time(value)


TYPE_LABELS = {
    ContentType.VIDEO.value: "Video",
    ContentType.PDF.value: "Notes (PDF)",
    ContentType.IMAGE.value: "Image",
}
TYPE_ICONS = {ContentType.VIDEO.value: "video", ContentType.PDF.value: "file", ContentType.IMAGE.value: "image"}


def plural(count: int, word: str, many: str | None = None) -> str:
    return f"{count} {word if count == 1 else (many or word + 's')}"


env = TEMPLATES.env
env.filters.update(duration=fmt_duration, size=fmt_size, time=fmt_time, ago=fmt_ago, date=fmt_date, until=fmt_until, date_value=date_value)
env.globals.update(
    PERMISSION_HELP=PERMISSION_HELP,
    TYPE_LABELS=TYPE_LABELS,
    TYPE_ICONS=TYPE_ICONS,
    plural=plural,
    accept_types=".mp4,.m4v,.pdf,.jpg,.jpeg,.png,.webp",
)


# --------------------------------------------------------------------------- responses


def _read_flash(request: Request) -> dict | None:
    raw = request.cookies.get(FLASH_COOKIE)
    if not raw:
        return None
    try:
        level, text = json.loads(base64.urlsafe_b64decode(raw.encode()).decode("utf-8"))
        return {"level": str(level)[:10], "text": str(text)[:2000]}
    except (ValueError, TypeError):
        return None


def _secure(response) -> None:
    response.headers["Content-Security-Policy"] = CSP
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"


def render(request: Request, template: str, context: dict | None = None, status_code: int = 200) -> HTMLResponse:
    flash = _read_flash(request)
    ctx = {
        "request": request,
        "staff": getattr(request.state, "staff", None),
        "csrf_token": getattr(request.state, "csrf_token", ""),
        "flash": flash,
        "path": request.url.path,
        **(context or {}),
    }
    response = TEMPLATES.TemplateResponse(request, template, ctx, status_code=status_code)
    if flash:
        response.delete_cookie(FLASH_COOKIE, path="/admin")
    _secure(response)
    return response


def redirect(url: str, message: str | None = None, level: str = "success") -> RedirectResponse:
    response = RedirectResponse(url, status_code=303)
    if message:
        payload = base64.urlsafe_b64encode(json.dumps([level, message[:1500]]).encode("utf-8")).decode()
        response.set_cookie(FLASH_COOKIE, payload, max_age=60, path="/admin", httponly=True, samesite="strict")
    return response


def safe_admin_path(value: str | None, default: str = "/admin/") -> str:
    """Only same-site dashboard paths (no scheme/host, no //evil)."""
    if not value:
        return default
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or not parts.path.startswith("/admin") or value.startswith("//"):
        return default
    return value


def back(request: Request, default: str = "/admin/") -> str:
    """Where the browser came from, if that was a dashboard page."""
    referer = request.headers.get("referer")
    if not referer:
        return default
    parts = urlsplit(referer)
    if parts.netloc and parts.netloc.lower() != request.headers.get("host", "").lower():
        return default
    path = parts.path + (f"?{parts.query}" if parts.query else "")
    return safe_admin_path(path, default)
