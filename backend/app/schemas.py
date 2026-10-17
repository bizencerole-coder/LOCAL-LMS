"""Request and response models for the student API.

The current app uses the module/content endpoints. The chapter/video models at the end
keep earlier app versions working (videos only).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100, description="Username or student ID")
    password: str = Field(min_length=1, max_length=256)


class NamedRef(BaseModel):
    id: uuid.UUID
    name: str


# Kept as a name for the class reference in /me.
ClassInfo = NamedRef


class StudentSummary(BaseModel):
    id: uuid.UUID
    full_name: str
    class_name: str | None
    batch_name: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    student: StudentSummary


class MeResponse(BaseModel):
    id: uuid.UUID
    student_code: str
    username: str
    full_name: str
    school_class: NamedRef | None = Field(serialization_alias="class")
    batch: NamedRef | None = None


class SubjectOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    sort_order: int
    module_count: int
    content_count: int
    video_count: int
    notes_count: int
    image_count: int
    # How many of those items this student has completed (watched, or opened for notes/images).
    completed_count: int = 0
    # Older app versions read this name.
    chapter_count: int


class ModuleOut(BaseModel):
    id: uuid.UUID
    subject_id: uuid.UUID
    title: str
    description: str | None
    sort_order: int
    content_count: int
    video_count: int
    notes_count: int
    image_count: int
    completed_count: int = 0


class ContentProgressOut(BaseModel):
    content_id: uuid.UUID
    position_seconds: int
    duration_seconds: int | None
    is_completed: bool
    last_watched_at: datetime | None


class ContentOut(BaseModel):
    id: uuid.UUID
    module_id: uuid.UUID
    type: str
    title: str
    description: str | None
    sort_order: int
    duration_seconds: int | None
    file_size_bytes: int | None
    progress: ContentProgressOut | None


class ContentDetailOut(ContentOut):
    module_title: str
    subject_id: uuid.UUID
    subject_name: str


class ContinueItemOut(BaseModel):
    content: ContentOut
    module_title: str
    subject_name: str


class ContentAccessOut(BaseModel):
    content_id: uuid.UUID
    type: str
    title: str
    url: str
    expires_at: datetime
    mime_type: str
    duration_seconds: int | None
    file_size_bytes: int | None
    resume_position_seconds: int
    is_completed: bool


class ProgressUpdate(BaseModel):
    # strict: JSON numbers only (no "123" strings or booleans), like the other schemas.
    model_config = ConfigDict(strict=True)

    position_seconds: float = Field(ge=0, le=7 * 24 * 3600)
    duration_seconds: float | None = Field(default=None, ge=0, le=7 * 24 * 3600)
    is_completed: bool = False


class HealthOut(BaseModel):
    status: str


class ReadyOut(BaseModel):
    status: str
    checks: dict[str, str]


# --------------------------------------------------------------- legacy (app <= 1.0.x)


class ChapterOut(BaseModel):
    id: uuid.UUID
    subject_id: uuid.UUID
    title: str
    description: str | None
    sort_order: int
    video_count: int


class ProgressOut(BaseModel):
    video_id: uuid.UUID
    position_seconds: int
    duration_seconds: int | None
    is_completed: bool
    last_watched_at: datetime | None


class VideoOut(BaseModel):
    id: uuid.UUID
    chapter_id: uuid.UUID
    title: str
    description: str | None
    duration_seconds: int | None
    sort_order: int
    progress: ProgressOut | None


class VideoDetailOut(VideoOut):
    chapter_title: str
    subject_id: uuid.UUID
    subject_name: str


class RecentVideoOut(BaseModel):
    video: VideoOut
    chapter_title: str
    subject_name: str


class PlaybackResponse(BaseModel):
    video_id: uuid.UUID
    title: str
    playback_url: str
    expires_at: datetime
    duration_seconds: int | None
    mime_type: str
    resume_position_seconds: int
    is_completed: bool
