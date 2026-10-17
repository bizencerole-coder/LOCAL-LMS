# API reference (v1)

Base: `http://<server>` through Nginx. Interactive docs: `http://<server>/docs`
(disable with `ENABLE_API_DOCS=false`). All `/api/v1` routes except login need
`Authorization: Bearer <access_token>`. This is the student app's API; the staff
dashboard is described at the end.

Errors always look like:

```json
{"error": {"code": "not_found", "message": "This item is not available."}, "request_id": "4f9c…"}
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
| 503 | `media_unavailable` | The item is published but its file is missing or unreadable |
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
  "student": {"id": "uuid", "full_name": "Demo Student", "class_name": "Class 12", "batch_name": "Batch 2026-27"}
}
```

`POST /api/v1/auth/logout` → 204. Revokes the current token.

`GET /api/v1/me`
```json
{"id": "uuid", "student_code": "DEMO-12-001", "username": "demo.student", "full_name": "Demo Student",
 "class": {"id": "uuid", "name": "Class 12"}, "batch": {"id": "uuid", "name": "Batch 2026-27"}}
```

## Catalogue

A student sees the subjects of their own class while the class and its batch are active,
the published modules of active subjects, and the published items in them.

`GET /api/v1/subjects`
```json
[{"id": "uuid", "name": "Computer Science", "description": null, "sort_order": 1,
  "module_count": 1, "content_count": 3, "video_count": 2, "notes_count": 1, "image_count": 0,
  "chapter_count": 1}]
```
(`chapter_count` equals `module_count`, for app 1.0.)

`GET /api/v1/subjects/{subject_id}/modules`
```json
[{"id": "uuid", "subject_id": "uuid", "title": "Python Basics", "description": null, "sort_order": 1,
  "content_count": 3, "video_count": 2, "notes_count": 1, "image_count": 0}]
```

`GET /api/v1/modules/{module_id}/contents`
```json
[{"id": "uuid", "module_id": "uuid", "type": "video", "title": "Lesson 2: Python Functions",
  "description": null, "sort_order": 2, "duration_seconds": 480, "file_size_bytes": 74198955,
  "progress": {"content_id": "uuid", "position_seconds": 120, "duration_seconds": 480,
               "is_completed": false, "last_watched_at": "2026-10-15T14:30:00Z"}},
 {"id": "uuid", "module_id": "uuid", "type": "pdf", "title": "Python Basics: Notes", "description": null,
  "sort_order": 5, "duration_seconds": null, "file_size_bytes": 2150, "progress": null}]
```
`type` is `video`, `pdf` (shown as *Notes*) or `image`; apps should treat other values as
an item they cannot open. `progress` is `null` for items not started. Storage paths are never returned.

`GET /api/v1/contents/{content_id}` — one item, plus `module_title`, `subject_id`, `subject_name`.

`GET /api/v1/me/continue?limit=10&include_completed=false` — recently watched or opened
items that are still available, newest first. `include_completed=false` gives the videos
in progress (*Continue watching*); `true` everything recent (*My Learning*):
```json
[{"content": {…ContentOut…}, "module_title": "Python Basics", "subject_name": "Computer Science"}]
```

## Opening an item

`POST /api/v1/contents/{content_id}/open`
```json
{
  "content_id": "uuid",
  "type": "video",
  "title": "Lesson 2: Python Functions",
  "url": "http://192.168.10.10/media/batch-2026-27/class12/computer-science/01-python-basics/02-python-functions.mp4?expires=1792076400&sid=…&md5=…",
  "expires_at": "2026-10-15T16:00:00Z",
  "mime_type": "video/mp4",
  "duration_seconds": 480,
  "file_size_bytes": 74198955,
  "resume_position_seconds": 120,
  "is_completed": false
}
```

Fetch `url` directly (no Authorization header needed). Nginx answers `HEAD`, `GET` and
`Range` (206) with the file's type (`video/mp4`, `application/pdf`, `image/jpeg|png|webp`).
403 = bad signature, 410 = expired → open the item again for a new URL. Opening notes or
an image records it as viewed (it then counts as completed and appears in *My Learning*).

## Progress

`GET /api/v1/contents/{content_id}/progress` → progress object (position 0 if never watched).

`PUT /api/v1/contents/{content_id}/progress`
```json
{"position_seconds": 765, "duration_seconds": 1200, "is_completed": false}
```
Upserts; safe to retry (retries never create a second row). The student comes from the
token (a `student_id` in the body is ignored). Position is clamped to the duration;
`is_completed` becomes true when the position reaches `COMPLETION_THRESHOLD` × duration
(seeking there counts) or when sent as true, and then stays true. The response is this
request's own result. Concurrent saves for the same student and item (two devices) are
last-writer-wins.

## Endpoints for app 1.0 (deprecated)

App 1.0 browses chapters and videos. These endpoints still work, on the same data, and
only ever return video items: `GET /api/v1/subjects/{id}/chapters` (modules),
`GET /api/v1/chapters/{id}/videos`, `GET /api/v1/videos/{id}`, `GET /api/v1/me/recent`,
`POST /api/v1/videos/{id}/playback` (returns `playback_url`), and
`GET|PUT /api/v1/videos/{id}/progress` (objects carry `video_id`). They will be removed once
every tablet runs app 1.1.

## Staff dashboard

`/admin/` is a server-rendered web application for staff (HTML pages, not a JSON API):
sign-in at `/admin/login` sets an HttpOnly, SameSite=Strict session cookie scoped to
`/admin`; every form post carries a CSRF token and is checked against the `Origin` header;
pages are sent with a strict Content-Security-Policy. File uploads go to
`PUT /admin/upload/{module_id}?filename=…&publish=true` with the raw file as the body and
the CSRF token in `X-CSRF-Token`; the response is `{"ok": true, "id": …, "type": …, "status": …, "problems": […]}`
or `{"ok": false, "error": "…"}`. Media previews for staff use the same signed `/media/` URLs
with `sid=staff-<id>`.
