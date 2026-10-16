"""Runtime configuration, read from environment variables.

Every setting maps to an upper-case environment variable of the same name
(``database_url`` -> ``DATABASE_URL``). See ``deploy/.env.example``.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# The signing secret is substituted into the Nginx config, so it must not contain
# characters Nginx would treat specially ($, quotes, spaces, semicolons).
_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{32,}$")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    database_url: str

    # Directory holding the MP4 library, as seen by this process.
    video_root: Path = Path("/srv/campus-lms/videos")

    # Shared with Nginx (secure_link). Generate with:
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    media_signing_secret: str = Field(repr=False)

    # Absolute base for playback URLs, e.g. "http://lms.campus.lan". When empty the
    # API uses the scheme/host the client used to reach it (via Nginx).
    media_base_url: str | None = None
    # Must match the Nginx media location.
    media_url_prefix: str = "/media/"

    # Database connections per API worker, and how long a request may wait for one.
    db_pool_size: int = Field(default=10, ge=1, le=100)
    db_max_overflow: int = Field(default=20, ge=0, le=200)
    db_pool_timeout_seconds: float = Field(default=5.0, ge=0.5, le=60)
    # Requests admitted into a worker at once (defaults to the connection pool size),
    # and how long an extra request queues before getting 503 service_busy. Must stay
    # below Nginx's proxy_read_timeout (30 s).
    db_admission_limit: int | None = Field(default=None, ge=1, le=500)
    db_admission_wait_seconds: float = Field(default=10.0, ge=0.5, le=25)

    playback_url_ttl_seconds: int = Field(default=7200, ge=60, le=86400)
    session_ttl_seconds: int = Field(default=28800, ge=300, le=7 * 86400)

    # Fraction of the duration after which a lesson counts as completed.
    # 0 disables automatic completion (only an explicit client flag completes).
    completion_threshold: float = Field(default=0.9, ge=0.0, le=1.0)

    # Verify the file exists before issuing a playback URL (clear error instead of a
    # player failure). Requires the video directory to be mounted into the API.
    check_media_file_on_playback: bool = True

    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"
    enable_api_docs: bool = True

    @field_validator("media_signing_secret")
    @classmethod
    def _validate_secret(cls, value: str) -> str:
        if not _SECRET_RE.match(value):
            raise ValueError(
                "MEDIA_SIGNING_SECRET must be at least 32 characters using only "
                "A-Z, a-z, 0-9, '-' or '_'. Generate one with: "
                'python -c "import secrets; print(secrets.token_urlsafe(48))"'
            )
        return value

    @field_validator("media_base_url")
    @classmethod
    def _validate_base_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("MEDIA_BASE_URL must start with http:// or https://")
        return value

    @field_validator("media_url_prefix")
    @classmethod
    def _validate_prefix(cls, value: str) -> str:
        if not (value.startswith("/") and value.endswith("/")):
            raise ValueError("MEDIA_URL_PREFIX must start and end with '/'")
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        value = value.upper()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
            raise ValueError("LOG_LEVEL must be DEBUG, INFO, WARNING or ERROR")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
