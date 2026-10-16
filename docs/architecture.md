# Architecture

## Components (PRD §6)

```
                    campus LAN / Wi-Fi (no WAN needed)
 ┌──────────────┐        ┌──────────────────── LMS host ─────────────────────┐
 │ Android      │  HTTP  │  Nginx :80                                        │
 │ tablet       ├───────▶│   /api/*, /health, /ready ──▶ FastAPI :8000 ──▶ PostgreSQL
 │ (Flutter +   │        │   /media/* (signed) ──▶ VIDEO_ROOT (read-only)    │   (internal network,
 │  ExoPlayer)  │        │   everything else ──▶ 404                         │    no published port)
 └──────────────┘        └───────────────────────────────────────────────────┘
```

| Component | Choice | Notes |
|---|---|---|
| App | Flutter, Android only | `video_player` (Android Media3/ExoPlayer). No Firebase, analytics, remote fonts or internet checks |
| API | FastAPI + SQLAlchemy 2 + Alembic | Sync endpoints in a thread pool; 2 Uvicorn workers by default |
| Database | PostgreSQL 17 | Docker volume `pgdata`; only reachable on the Compose network |
| Video | Nginx static files | `secure_link` signed URLs; Range/206 native; no transcoding |
| Storage | `VIDEO_ROOT` host folder (OMV shared folder or plain disk) | Mounted read-only into Nginx and the API |
| Deployment | Docker Compose | One host; logs to Docker's json-file driver with rotation |

## Main flows

**Sign-in.** `POST /api/v1/auth/login` checks the argon2id hash and returns an opaque
bearer token (32 random bytes). Only its SHA-256 is stored, in `sessions`. Every
authenticated request looks the session up and checks it is unexpired, not revoked,
and that the student is still active.

**Browsing.** All catalogue queries are built from one set of visibility rules
(`backend/app/access.py`): the student's own class, active class and subject,
published chapter, published video. Anything else returns 404.

**Playback.**

```
app ──POST /api/v1/videos/{id}/playback──▶ API: visible? file present? ──▶ signed URL
app ──GET /media/<storage_key>?expires=…&sid=…&md5=… (Range: bytes=…)──▶ Nginx ──▶ file
```

The API signs `md5("{expires}{uri}{sid} {secret}")` (base64url). Nginx's
`secure_link_md5` recomputes it from the request and the shared secret: a missing or
wrong signature is 403, an expired one 410. The API is not involved again until the URL
expires, so every Range request from the player costs the API nothing. When the URL
expires (default 2 h) or the network drops, the app's **Try again** requests a fresh
URL and continues from the last position.

**Progress.** The app saves every 20 s while playing, on pause, on leaving the screen or
app, and at the end. Leaving the player hands the final save back to the calling screen,
which reloads only after it has been sent, so lists show the new position. The server
upserts on `(student_id, video_id)` with `RETURNING`, clamps the position to the duration,
marks completion when the position reaches `COMPLETION_THRESHOLD` × duration (or an
explicit flag from the app) and never un-completes a lesson. Failed saves are ignored by
the player and retried on the next tick; a failed completion save is re-sent until it
succeeds. Concurrent saves from two devices are last-writer-wins.

**Overload.** Sync endpoints hold a pooled database connection from authentication until
the response is sent. A pure-ASGI admission gate limits each worker to pool-size +
overflow requests in flight (30 by default) and answers 503 `service_busy` with
`Retry-After` after 10 s of queueing, so a burst from a whole class degrades to quick
retries instead of 30-second stalls and 504s. The pool itself times out after 5 s for
the same reason.

## Decisions

| Decision | Why |
|---|---|
| **Nginx `secure_link` URLs** for media authorization (open decision §24.5) | Simplest secure option that keeps Range requests on Nginx. `auth_request`/`X-Accel-Redirect` would call the API on every Range request. The URL is useless without the secret, cannot be re-pointed at another file, and expires. |
| Student ID (`sid`) in the signed URL | Lets Nginx media logs be tied to a student for diagnosis (AC-10) and means one student's URL cannot be relabelled as another's. |
| **Opaque DB sessions** instead of JWT (§8.7) | Sign-out and deactivation take effect immediately (revocation), there is no token-signing key to manage, and the lookup is one indexed query — negligible at prototype scale. |
| 404 (not 403) for content outside the student's access | IDs of other classes' or unpublished lessons cannot be probed. |
| argon2id at 19 MiB / t=2 / p=1 | OWASP minimum; the library default (64 MiB) could exhaust RAM if a whole class signs in at once. |
| Login throttling in Nginx (10/min per IP, burst 5) | Per-IP rather than per-account, so a classmate cannot lock another student out. |
| Progressive MP4, no HLS | PRD §5.6. Revisit after load tests (§20 F1). |
| `video_player` (ExoPlayer) for the prototype player (open decision §24.3) | Maintained by the Flutter team, uses Android Media3/ExoPlayer, supports seek, speed and network URLs. The player is isolated in `mobile/lib/player/` so it can be swapped for `media_kit` if tablet tests show problems. **Must be validated on the real tablets.** |
| Admin via server-side CLI (open decision §24.7) | Meets FR-08 without exposing admin endpoints on the network: only someone with a shell on the server can change content or accounts. A web admin can follow later (§20 F3). |
| Pure-Python MP4 inspector | Duration, resolution, codecs and fast-start check without installing FFmpeg on the server. |
| Migrations run on API start | Simple for the prototype; disable with `MIGRATE_ON_START=false` for controlled upgrades. |

## Data model

As PRD §8, plus:

- `videos.sort_order` — lesson order within a chapter (§10.3).
- `student_video_progress.completed_at` — when completion first happened.
- `sessions` — `token_hash` (unique), `expires_at`, `revoked_at`.
- Unique constraints: `classes.name`, `(subjects.class_id, name)`,
  `(chapters.subject_id, title)`, `videos.storage_key`, `students.username`,
  `students.student_code`, `(student_video_progress.student_id, video_id)`.
- `student_code` is stored upper-case and `username` lower-case; sign-in accepts either,
  case-insensitively.
- Storage keys are validated (`[A-Za-z0-9._-]` path segments, `.mp4`/`.m4v`, no `..`), so a
  key can never point outside `VIDEO_ROOT` and never needs URL encoding.

## Security summary (PRD §13)

- Passwords: argon2id hashes only. Tokens: random, stored hashed, revocable.
- Student identity always comes from the session, never from a request body.
- Server-side visibility checks on every catalogue, playback and progress request.
- Nginx serves only `/media/` with a valid signature; no directory listing, no other files,
  GET/HEAD only (405 otherwise), directories answer 404, private-network allowlist,
  `server_tokens off`, `no-store` on API responses. Nginx overwrites `X-Forwarded-For`,
  so the client address in API logs cannot be spoofed.
- PostgreSQL is on an internal Docker network reachable only by the API; the API is
  reachable only by Nginx; neither publishes a port. Containers mount media read-only,
  drop all capabilities (Nginx keeps the few it needs to start) and run with
  `no-new-privileges`; the API runs as a non-root user on a read-only image.
- Logs omit passwords, tokens and URL signatures: Nginx logs `$uri`, not the query string,
  and its error log is limited to `crit` for `/media/` because error-log lines would
  include the signed request line.
- Secrets live in `deploy/.env` (git-ignored); `.env.example` has placeholders. They are
  also visible to anyone with Docker access (`docker inspect`, `nginx -T`), which on the
  LMS host is the operator account; do not paste container configuration into tickets.

## Known limitations

- **HTTP only.** Credentials and tokens cross the Wi-Fi unencrypted. Acceptable only on an
  isolated, WPA2/3-protected prototype network. Production needs local TLS (§20 F4); the
  Android app then drops `usesCleartextTraffic`.
- **Issued URLs outlive unpublishing.** Unpublishing or deactivating stops *new*
  authorizations immediately, but a URL already issued stays valid until it expires
  (`PLAYBACK_URL_TTL_SECONDS`, default 2 h). Lower the TTL if this matters.
- **A signed URL can be shared** with another device on the LAN until it expires. Binding it
  to the client IP (`$remote_addr`) is possible but breaks when tablets roam between APs
  with different DHCP scopes; evaluate after the Wi-Fi survey.
- **No content protection** against screen recording or copying (PRD §13).
- **No admin web UI**; content and accounts are managed with the CLI.
- **Login throttling is per IP only** (in Nginx); there is no per-account lockout.
- **The Nginx allowlist does not cover responses made with `return`** (`/nginx-health`,
  the 404 catch-all, the media 403/410 signature checks), which answer before allow/deny
  runs. Denied clients still get no API data or video bytes.
- **Errors generated by Nginx itself** (429, 413, 414, 502–504) are HTML pages, not the
  JSON error envelope; the app handles them by status code.
- **Docker Desktop hides client addresses** (every client is the Docker gateway), so the
  allowlist, the per-IP login throttle and per-client log views only work on a Linux host.
- **Single host, no HA**: if the server, switch, AP or power fails, playback stops.
- **Capacity is unmeasured.** No claim of 500 concurrent viewers (PRD §14, §21).
- The Flutter player choice is provisional until tested on the target tablets.
