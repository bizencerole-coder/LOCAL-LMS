# API reference (v1)

Base: `http://<server>` through Nginx. Interactive docs: `http://<server>/docs`
(disable with `ENABLE_API_DOCS=false`). All `/api/v1` routes except login need
`Authorization: Bearer <access_token>`.

Errors always look like:

```json
{"error": {"code": "not_found", "message": "This lesson is not available."}, "request_id": "4f9c…"}
```

| Status | `code` | When |
|---|---|---|
| 401 | `invalid_credentials` | Wrong username/password (same response for unknown users) |
| 400 | `bad_request` | A value the database cannot store, or no usable `Host` header (set `MEDIA_BASE_URL`) |
| 401 | `unauthorized` | Missing, expired or revoked token; student deactivated |
| 403 | `account_inactive` | Correct password for an inactive account |
| 404 | `not_found` | Item does not exist **or** the student may not see it |
| 422 | `validation_error` | Bad request body; `error.fields` lists problems. Numbers must be JSON numbers (not strings or booleans) |
| 429 | — (Nginx) | More than 10 login attempts/min from one IP |
| 503 | `media_unavailable` | Lesson is published but its file is missing or unreadable |
| 503 | `service_busy` | Too many requests in flight on the server; `Retry-After: 2`. The app's progress saver retries on its own |
| 500 | `internal_error` | Unexpected error; the `request_id` is in the API log with the traceback |

Errors that Nginx generates itself (429, 413, 414, 405 for unknown methods, and 502/503/504
while the API is down) are HTML pages without the JSON envelope or a `request_id`; the app
handles them by status code.

## Health

| Request | Response |
|---|---|
| `GET /health` | `{"status": "ok"}` — process is up (no DB access) |
| `GET /ready` | `{"status": "ok", "checks": {"database": "ok", "media_storage": "ok"}}`, or 503 with `"degraded"` |
| `GET /nginx-health` | `ok` — served by Nginx itself |

## Authentication

`POST /api/v1/auth/login`

```json
{"username": "demo.student", "password": "…"}
```
`username` may also be the student code. Response:
```json
{
  "access_token": "…",
  "token_type": "bearer",
  "expires_in": 28800,
  "student": {"id": "uuid", "full_name": "Demo Student", "class_name": "Class 12"}
}
```

`POST /api/v1/auth/logout` → 204. Revokes the current token.

`GET /api/v1/me`
```json
{"id": "uuid", "student_code": "DEMO-12-001", "username": "demo.student",
 "full_name": "Demo Student", "class": {"id": "uuid", "name": "Class 12"}}
```

## Catalogue

`GET /api/v1/subjects`
```json
[{"id": "uuid", "name": "Computer Science", "sort_order": 1, "chapter_count": 1, "video_count": 2}]
```

`GET /api/v1/subjects/{subject_id}/chapters`
```json
[{"id": "uuid", "subject_id": "uuid", "title": "Python Basics", "description": null,
  "sort_order": 1, "video_count": 2}]
```

`GET /api/v1/chapters/{chapter_id}/videos`
```json
[{"id": "uuid", "chapter_id": "uuid", "title": "Lesson 2: Python Functions", "description": null,
  "duration_seconds": 480, "sort_order": 2,
  "progress": {"video_id": "uuid", "position_seconds": 120, "duration_seconds": 480,
               "is_completed": false, "last_watched_at": "2026-10-15T14:30:00Z"}}]
```
`progress` is `null` for lessons not started. Storage paths are never returned.

`GET /api/v1/videos/{video_id}` — one lesson, plus `chapter_title`, `subject_id`, `subject_name`.

`GET /api/v1/me/recent?limit=10&include_completed=true` — recently watched lessons that
are still available, newest first:
```json
[{"video": {…VideoOut…}, "chapter_title": "Python Basics", "subject_name": "Computer Science"}]
```

## Playback

`POST /api/v1/videos/{video_id}/playback`
```json
{
  "video_id": "uuid",
  "title": "Lesson 2: Python Functions",
  "playback_url": "http://192.168.10.10/media/class12/computer-science/01-python-basics/02-python-functions.mp4?expires=1792076400&sid=…&md5=…",
  "expires_at": "2026-10-15T16:00:00Z",
  "duration_seconds": 480,
  "mime_type": "video/mp4",
  "resume_position_seconds": 120,
  "is_completed": false
}
```

Fetch `playback_url` directly (no Authorization header needed). Nginx answers `HEAD`,
`GET` and `Range` (206). 403 = bad signature, 410 = expired → request a new URL.

## Progress

`GET /api/v1/videos/{video_id}/progress` → progress object (position 0 if never watched).

`PUT /api/v1/videos/{video_id}/progress`
```json
{"position_seconds": 765, "duration_seconds": 1200, "is_completed": false}
```
Upserts; safe to retry (retries never create a second row). The student comes from the
token (a `student_id` in the body is ignored). Position is clamped to the duration;
`is_completed` becomes true when the position reaches `COMPLETION_THRESHOLD` × duration
(seeking there counts) or when sent as true, and then stays true. The response is this
request's own result. Concurrent saves for the same student and lesson (two devices) are
last-writer-wins.
