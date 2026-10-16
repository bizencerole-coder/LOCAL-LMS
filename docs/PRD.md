# Campus LMS — Prototype PRD and Future Architecture Plan

**Document type:** Product Requirements Document (PRD) and Technical Implementation Plan  
**Project:** Campus LMS — Local Campus Video Learning Platform  
**Prepared for:** Bizence development team  
**Version:** 1.0  
**Status:** Prototype scope approved; implementation-ready draft  
**Primary focus:** Functional framed prototype using local video storage, local LMS API/database, and a native Android application  
**Future target:** Reliable local video delivery for up to 500 concurrent students over campus Wi-Fi  
**Date:** 15 October 2026

---

## 1. Executive Summary

Campus LMS is a campus-local learning application for students to access recorded lessons stored on an organization's local server. Students use a native Android tablet application over the campus Wi-Fi. Core playback must not depend on public internet access.

The immediate deliverable is a **working, framed prototype**, not a full commercial LMS. It must prove the complete core flow:

1. A local server stores and serves video files.
2. A local backend authenticates prototype users and returns course/video metadata.
3. A native Android app lists classes, subjects, chapters, and lessons.
4. A student selects a lesson and streams it from the local server.
5. Playback works when public internet access is disconnected, provided the local network and server remain available.
6. The app saves and restores playback progress.
7. A basic local admin workflow allows prototype content and users to be prepared.
8. The system logs enough information to diagnose playback and network problems.

The prototype should be designed so that it can evolve into a production platform for 500 concurrent viewers. However, **supporting 500 viewers is a future capacity objective, not a claim that the prototype supports 500 until measured and validated**.

The initial delivery approach is intentionally simple: one Linux host can run the LMS API, PostgreSQL, Nginx, and local video storage. OpenMediaVault (OMV) may be used for storage management if a suitable existing machine is available. If there is no suitable existing machine, the team can use a fresh PC or server. Hardware purchase should follow an inventory and test, not precede it.

---

## 2. Product Vision

Provide a reliable, easy-to-use campus video-learning experience in which students can watch assigned recorded lessons from a local server without consuming public internet bandwidth or depending on cloud video services.

### 2.1 Product goals

- Deliver recorded lessons to Android tablets over campus LAN/Wi-Fi.
- Keep core course browsing, authentication, playback, and progress tracking available without public internet.
- Keep the initial architecture cost-effective and maintainable.
- Validate video delivery and user experience on actual tablets.
- Establish measurable test results to inform future server and Wi-Fi investment.
- Build a clean separation between LMS APIs and video delivery.
- Avoid unnecessary scope until the local streaming path is proven.

### 2.2 Non-goals for the framed prototype

The following are **not** required in the first prototype:

- Live streaming or video conferencing.
- Online payments or subscriptions.
- Public access from outside the campus.
- iOS application.
- Full school ERP integration.
- Attendance, fees, examinations, marks, messaging, or timetable modules.
- AI recommendations or AI tutors.
- DRM or a guarantee that students cannot screen-record or copy content.
- Offline video downloads.
- Advanced adaptive bitrate streaming unless the MP4 test demonstrates a need.
- Multi-campus tenancy.
- High availability, automatic failover, or production disaster recovery.
- A claim of verified support for 500 concurrent students before load testing.

---

## 3. Users and Roles

### 3.1 Student

Can:
- Sign in with a prototype account.
- View the classes/courses assigned to that account.
- Browse subjects, chapters, and published lessons.
- Start, pause, seek, and resume a video.
- See last-watched progress.
- Sign out.

Cannot:
- Browse arbitrary filesystem paths.
- Access unpublished videos unless explicitly authorized.
- Access another student's progress.
- create or edit content.

### 3.2 Content administrator (prototype)

Can:
- Sign in to a simple local admin interface or use a documented seed/import process.
- Create/edit classes, subjects, chapters, and videos.
- Set a video as draft or published.
- Associate students with classes.
- Check video file availability and metadata.

The admin workflow can be intentionally minimal for the prototype. If a polished admin UI would delay the main playback test, provide a basic web page or a documented CLI/seed script first.

### 3.3 System operator/developer

Can:
- Configure server services and storage.
- Inspect logs and health checks.
- Run load tests.
- Manage backups and configuration.
- Diagnose client/server/network errors.

---

## 4. Success Criteria and Acceptance Criteria

### 4.1 Prototype success

The prototype is successful when a developer can set up the system from the documentation and demonstrate this end-to-end flow on at least two physical Android tablets:

1. Connect tablets to the campus/local Wi-Fi.
2. Open the app and sign in with local test accounts.
3. Browse seeded course content.
4. Start two different videos from the local server.
5. Seek within both videos.
6. Disconnect the public internet while keeping LAN/Wi-Fi active.
7. Continue playing and open another locally available video.
8. Close and reopen a lesson and resume from the saved position.
9. Verify progress is stored in PostgreSQL.
10. Verify API and video logs show the sessions and any errors.

### 4.2 Required measurable criteria

| ID | Requirement | Acceptance target |
|---|---|---|
| AC-01 | Local authentication | Valid test account can sign in without an external identity provider |
| AC-02 | Course browsing | Seeded class/subject/chapter/video data appears correctly |
| AC-03 | Local playback | Video streams from a private LAN address/hostname |
| AC-04 | Internet independence | Core playback continues with WAN disconnected while local LAN remains up |
| AC-05 | Playback controls | Play/pause, seek, full-screen, and supported speed control work |
| AC-06 | Resume | Saved position is restored within a reasonable tolerance (target ±10 seconds) |
| AC-07 | Access control | Student cannot obtain an authorized playback URL for an unassigned/unpublished video |
| AC-08 | HTTP range | Video server correctly supports byte-range requests for MP4 seeking |
| AC-09 | Progress API | Progress saves and reads correctly after app restart |
| AC-10 | Diagnostics | API errors and Nginx access errors can be investigated from logs |
| AC-11 | No public dependency | App startup and core lesson playback do not require Firebase, cloud APIs, public DNS, or CDN |
| AC-12 | Setup reproducibility | Another developer can follow this document and bring up the prototype |

### 4.3 Non-functional target for the initial small test

For 2–5 test devices on a healthy local network:
- No repeated buffering should occur with properly encoded test videos.
- Video startup should normally be within 3 seconds, but actual results must be recorded rather than assumed.
- No application crash during a 30-minute supervised playback test.
- The server should not require GPU transcoding.
- Public internet may be disconnected without interrupting established local video delivery.

These are initial test targets, not production guarantees.

---

## 5. Assumptions and Constraints

1. The organization has or can prepare a local PC/server.
2. The team has prior experience with OpenMediaVault file storage.
3. The campus has approximately 11–20 Wi-Fi access points, but exact models, placement, uplink speeds, and capacity remain unknown.
4. Initial source videos are primarily 720p.
5. The initial prototype will use Android tablets.
6. The first content delivery method will be HTTP progressive MP4.
7. A future HLS delivery option may be added if testing shows a clear benefit.
8. The local server, switches, Wi-Fi, and power must remain operational for local playback to work.
9. The system is intended for a private campus network. It must not be exposed directly to the public internet during the prototype.
10. Hardware capacity is not assumed. It must be measured.

---

## 6. Architecture Decisions

### 6.1 Prototype architecture

Start with a single physical host for the API, database, HTTP video server, and storage, unless the existing OMV machine should remain a dedicated NAS. The simplest viable deployment is preferred.

**Logical components:**

- **Flutter Android app:** student UI and native-backed video playback.
- **FastAPI:** local authentication, course metadata, authorization, and playback progress.
- **PostgreSQL:** structured local data.
- **Nginx:** static MP4 delivery with HTTP Range support.
- **OMV/local filesystem:** video storage and storage administration.
- **Local DNS or fixed private IP:** stable access to the service.
- **Monitoring/logs:** system health, API errors, HTTP requests, and network usage.

### 6.2 Recommended prototype deployment choices

| Component | Recommended choice | Reason |
|---|---|---|
| Mobile app | Flutter | One codebase and suitable Android tablet support |
| API | FastAPI (Python) | Fast to implement and easy to document |
| Database | PostgreSQL | Reliable relational database, suitable for future growth |
| Video HTTP server | Nginx | Efficient static file delivery and Range support |
| Video container | MP4 | Simplest initial playback and seeking path |
| Video codec | H.264 + AAC | Broad Android compatibility |
| Player | Flutter package with Android native playback support | Must be validated on actual tablets |
| Storage | OMV-managed shared folder or local filesystem | Reuse existing knowledge/equipment |
| Deployment | Docker Compose where compatible with chosen OMV/Linux setup | Repeatable service deployment |
| API documentation | OpenAPI/Swagger generated by FastAPI | Easier integration and testing |

**Player selection note:** Evaluate `media_kit` and/or a maintained player backed by Android Media3/ExoPlayer. Select one after testing MP4 playback, seek behavior, full-screen, speed control, and compatibility with target tablets. Do not commit to a package before validating its current maintenance status and Android behavior.

### 6.3 Video delivery must bypass the API

The backend should authorize a video and return a URL. The Flutter app should then stream directly from Nginx. The API must not read the video file and proxy every byte.

This keeps API workers free for authentication, metadata, and progress requests.

### 6.4 No runtime transcoding

Do not transcode a video each time a student opens it. Use pre-encoded video files. FFmpeg may be used offline during content preparation.

### 6.5 Prototype network model

Example only; confirm the subnet does not conflict with the existing campus LAN.

- Router/gateway: `192.168.10.1`
- LMS host: `192.168.10.10`
- Local hostname: `lms.campus.lan` (requires local DNS configuration)
- Students: DHCP-assigned addresses
- API: TCP port `8000` behind Nginx in development, or a reverse-proxied local path in the integrated setup
- Video: Nginx on TCP port `80` or `8080` during initial tests

For a more production-like local deployment, expose one local hostname and reverse-proxy API paths (for example `/api/`) and video paths (for example `/media/`) through Nginx. Use firewall rules to prevent access from untrusted networks.

---

## 7. Functional Requirements

### FR-01 — Local student authentication

- Student signs in using username/student ID and password.
- Passwords must be stored as strong hashes, never plain text.
- API returns a short-lived access token or a secure session.
- Invalid credentials show a generic error.
- Sign-out removes the local session.
- No external OAuth/Firebase dependency in the core path.
- Rate-limit repeated login attempts at the API or reverse proxy.
- Initial prototype can use seeded accounts; bulk student import is a later enhancement.

### FR-02 — Course browsing

- Student sees only assigned/available classes and courses.
- Subject lists are retrieved from the API.
- Chapters are ordered by a sequence field.
- Only published lessons are displayed.
- Empty states and API errors are shown clearly.
- The app must not hard-code the full course catalogue.

### FR-03 — Video catalogue and metadata

Each video record should include:
- Unique ID
- Chapter ID
- Display title
- Description (optional)
- Storage key/path known only to the server
- Duration in seconds
- File size in bytes
- Resolution (optional metadata)
- Status: draft/published/archived
- Created/updated timestamps

The app must not send arbitrary storage paths to the server.

### FR-04 — Playback authorization

- App requests playback permission by video ID.
- Backend checks the user's status, course assignment, and video publication status.
- If authorized, backend returns a local playback URL or short-lived signed/tokenized local URL.
- If unauthorized, the request is rejected.
- Nginx must not expose the entire storage directory or directory listings.
- The URL/token design must avoid long-lived public links. For the prototype, a short-lived token or an authorization endpoint is preferred.
- The final design must be tested carefully: a URL that is merely hidden in the app is not access control.

**Implementation note:** Nginx `X-Accel-Redirect`/internal locations or a short-lived signed URL scheme may be considered. Select the simplest secure approach that supports Range requests. Do not put video bytes through FastAPI.

### FR-05 — MP4 streaming

- Nginx serves pre-encoded MP4 files.
- HTTP `GET` and `HEAD` work as expected.
- `Accept-Ranges: bytes` and `206 Partial Content` behavior is verified.
- Seeking works from beginning, middle, and near the end of a test video.
- MIME type for MP4 is correct.
- File paths are not directly guessable or exposed through directory browsing.
- Missing or unavailable files return a clear HTTP error and a log entry.
- The server does not transcode during playback.

### FR-06 — Video player

The player screen must support:
- Play/pause
- Timeline and seeking
- Full-screen
- Current time and total duration
- Loading/error state
- Retry after a recoverable network error
- Resume from last saved position
- Playback speed if supported reliably by the chosen player
- Screen orientation behavior suitable for tablets

Avoid adding downloads, DRM, casting, subtitles, or advanced picture-in-picture to the initial scope.

### FR-07 — Playback progress

- App reads the last saved position before playback or when lesson metadata is loaded.
- App periodically saves progress, e.g. every 15–30 seconds while playing.
- Save on pause, on exit, and when playback completes.
- Avoid sending a request every second.
- Progress is associated with both student ID and video ID.
- The backend validates that the student may access the video.
- Completion rule should be configurable; initial suggestion: mark complete when at least 90% is watched, but do not force completion logic if the school has not decided.
- The player should tolerate a failed progress update without stopping video playback.
- Progress writes should be idempotent or use an upsert so retries do not create duplicate records.

### FR-08 — Prototype content administration

Minimum acceptable content-management method:
- Seed script or a basic admin interface to create students, classes, subjects, chapters, and video metadata.
- Admin can map a metadata record to a file already uploaded to the video directory.
- Publish/unpublish a video.
- Verify the physical file exists and is readable.
- Prevent duplicate IDs and invalid parent-child associations.

For the framed prototype, a documented seed/import script is acceptable. A polished admin dashboard is not a blocker for the first playback demo.

### FR-09 — Health and diagnostics

Provide:
- `GET /health` for application health.
- Database connectivity check.
- Nginx service check.
- Logs with timestamps and request IDs where practical.
- API logs without passwords, access tokens, or sensitive data.
- Nginx access/error logs.
- A simple operator checklist to identify whether the API, database, storage, or Wi-Fi is failing.

### FR-10 — Internet independence

Core operations must work when the WAN connection is disconnected:
- Login using local credentials
- Browse locally stored course metadata
- Authorize playback
- Stream videos
- Save progress
- Resume videos

The app must not rely on public DNS for the LMS hostname. Configure local DNS or use a stable private IP during the first test.

Third-party analytics, push notifications, cloud identity, cloud licence checks, external fonts, and remote API calls must not be required for the core screens.

---

## 8. Data Model

A minimal PostgreSQL schema is recommended.

### 8.1 `students`

- `id` UUID primary key
- `student_code` unique, not null
- `full_name`
- `username` unique, not null
- `password_hash` not null
- `class_id` foreign key
- `is_active` boolean
- `created_at`
- `updated_at`

### 8.2 `classes`

- `id` UUID primary key
- `name` not null
- `description`
- `is_active`
- `created_at`

### 8.3 `subjects`

- `id` UUID primary key
- `class_id` foreign key
- `name` not null
- `sort_order`
- `is_active`

### 8.4 `chapters`

- `id` UUID primary key
- `subject_id` foreign key
- `title` not null
- `description`
- `sort_order`
- `is_published`

### 8.5 `videos`

- `id` UUID primary key
- `chapter_id` foreign key
- `title` not null
- `description`
- `storage_key` not null
- `duration_seconds`
- `file_size_bytes`
- `mime_type` default `video/mp4`
- `resolution_width`
- `resolution_height`
- `status` enum or constrained text (`draft`, `published`, `archived`)
- `created_at`
- `updated_at`

`storage_key` should be a relative, server-managed key, not an arbitrary client-supplied path.

### 8.6 `student_video_progress`

- `id` UUID primary key, or a composite key
- `student_id` foreign key
- `video_id` foreign key
- `position_seconds`
- `duration_seconds` (optional snapshot)
- `is_completed`
- `last_watched_at`
- Unique constraint on `(student_id, video_id)`

Use an upsert on `(student_id, video_id)`.

### 8.7 `sessions` or token strategy

Use a suitable token/session strategy. If JWT is selected:
- Sign with a secret stored in environment configuration.
- Set a reasonable expiry.
- Do not store secrets in source control.
- Consider refresh/revocation needs.
- Use TLS if credentials cross an untrusted network. A trusted isolated prototype LAN may use HTTP only for a temporary test, but production should use a carefully designed local TLS arrangement.

### 8.8 Relationships and indexes

- Index foreign keys and frequently filtered fields.
- Index `student_code`, `username`, `class_id`, `chapter_id`, and video status.
- Ensure progress lookup uses the unique student/video pair.
- Use migrations (for example Alembic) rather than manually changing the production schema.

---

## 9. API Contract (Initial Draft)

Use `/api/v1` as the versioned prefix.

### Authentication

`POST /api/v1/auth/login`

Request:
```json
{
  "username": "demo.student",
  "password": "DemoPassword123!"
}
```

Response (example):
```json
{
  "access_token": "<token>",
  "token_type": "bearer",
  "expires_in": 3600,
  "student": {
    "id": "uuid",
    "full_name": "Demo Student",
    "class_name": "Class 12"
  }
}
```

`GET /api/v1/me` — returns the authenticated student's profile.

### Course catalogue

- `GET /api/v1/subjects`
- `GET /api/v1/subjects/{subject_id}/chapters`
- `GET /api/v1/chapters/{chapter_id}/videos`

All responses must be filtered to content the student is permitted to access.

### Playback

`POST /api/v1/videos/{video_id}/playback`

Response (example):
```json
{
  "video_id": "uuid",
  "title": "Python Functions",
  "playback_url": "http://lms.campus.lan/media/<short-lived-token-or-authorized-key>",
  "expires_at": "2026-10-15T15:00:00Z",
  "duration_seconds": 1200
}
```

This is a contract example, not a final token implementation. Do not expose a permanent raw filesystem path. If the system uses an authorization cookie/header, validate that the chosen Flutter player can send it while supporting Range requests.

### Progress

`GET /api/v1/videos/{video_id}/progress`

`PUT /api/v1/videos/{video_id}/progress`

Request:
```json
{
  "position_seconds": 765,
  "duration_seconds": 1200,
  "is_completed": false
}
```

Response:
```json
{
  "video_id": "uuid",
  "position_seconds": 765,
  "is_completed": false,
  "last_watched_at": "2026-10-15T14:30:00Z"
}
```

The server must derive the student identity from the authenticated session/token, not accept a client-supplied `student_id` as authoritative.

### Health

- `GET /health`
- Optional: `GET /ready` for database and dependency readiness

Do not expose detailed secrets or internal configuration in health responses.

---

## 10. Application Screens and UX Requirements

### 10.1 Login screen
- Student ID/username and password.
- Login action and progress indicator.
- Clear local-server unavailable message.
- No public internet check.
- No third-party sign-in.

### 10.2 Home screen
- Student name/class.
- Subject cards/list.
- Continue Watching section.
- Local connection indicator (optional but useful for prototype).
- Retry action when the API is unavailable.

### 10.3 Subject/chapter screens
- Clear hierarchy: Class → Subject → Chapter → Video.
- Sort by configured sequence.
- Show published lessons only.
- Display duration where available.
- Show a friendly empty state.

### 10.4 Video player screen
- Video title.
- Player controls.
- Loading indicator.
- Recoverable error message and retry.
- Save/resume progress.
- Prevent multiple progress timers for the same player session.
- Stop timers and release the player when leaving the screen.

### 10.5 My Learning
- Recently watched videos.
- Last saved position.
- Continue button.

### 10.6 Admin workflow
For the first prototype, either:
1. A minimal local web admin page; or
2. A seed script plus a documented method to place videos and publish metadata.

The main milestone is end-to-end student playback. Do not delay it for a large admin UI.

---

## 11. Server and Storage Setup Plan

### 11.1 Hardware inventory before installation

Record:
- CPU model
- RAM
- System disk
- Video disk(s)
- Ethernet NIC speed
- Switch port speed
- OS/OMV version
- Current storage layout
- Current network subnet
- UPS availability

Do not reformat or repurpose a machine until existing data is backed up and the owner has approved the change.

### 11.2 Storage preparation

- Create a dedicated shared folder for LMS videos.
- Keep application data and video files logically separate.
- Use a filesystem with monitoring and sufficient free space.
- Restrict write access to the video upload/admin account.
- Nginx should have read-only access to published videos where feasible.
- Do not expose the NAS management interface to student VLANs.
- Back up database and configuration separately from the media library.

### 11.3 Video directory convention

Example:
```text
campus-lms/
  videos/
    class11/
      physics/
      chemistry/
    class12/
      computer-science/
      mathematics/
  imports/
  backups/
```

The exact mounted path depends on OMV. Use an environment variable such as `VIDEO_ROOT` and avoid hard-coding a device UUID in application code.

### 11.4 Nginx requirements

- Serve video with correct `video/mp4` MIME type.
- Support HTTP Range requests and seeking.
- Disable directory listing.
- Prevent path traversal.
- Use a dedicated read-only service identity where practical.
- Log status codes, bytes sent, and request duration where possible.
- Set appropriate connection/time-out values without excessive tuning at the prototype stage.
- Restrict routes to the local network.
- Implement an authorization design before publishing real student content.

### 11.5 Database and API deployment

- PostgreSQL should not be exposed directly to student tablets.
- API should be reachable only through the intended local service route.
- Use environment variables or a secrets file with restricted permissions.
- Do not commit `.env` files or secrets.
- Use schema migrations.
- Configure restart behavior and logs.
- Back up database data before upgrades.

### 11.6 Docker Compose

Docker Compose is a good default for repeatability if it is compatible with the selected OMV setup. The development team should supply:
- `compose.yaml`
- `.env.example` (no real secrets)
- Nginx config
- API Dockerfile
- Database initialization/migration commands
- Seed data script
- Start/stop/update instructions
- Backup/restore instructions

If OMV plugin or Docker configuration constraints make Compose unsuitable, run the services natively and document the alternative. Do not install competing container management layers without a reason.

---

## 12. Video Preparation Workflow

### 12.1 Initial supported format

- Container: MP4
- Video: H.264
- Audio: AAC
- Resolution: primarily 1280×720
- Fast-start metadata enabled for progressive playback
- Bitrate target: approximately 1–1.5 Mbps total as an initial test profile, adjusted for content quality

The target is a starting point. Inspect samples containing small text, code, equations, and diagrams to verify readability.

### 12.2 FFmpeg preparation

Use FFmpeg for offline encoding only when necessary. Keep an untouched source copy if storage permits.

Example command (validate on sample files before batch use):
```bash
ffmpeg -i input.mp4 \
  -c:v libx264 -preset medium -crf 23 \
  -vf "scale='min(1280,iw)':-2" \
  -c:a aac -b:a 128k \
  -movflags +faststart \
  output-720p.mp4
```

This command uses CRF, so output bitrate varies by source. If a strict target bitrate is required, use a controlled bitrate/two-pass profile and validate visual quality. Do not blindly re-encode already suitable source videos.

### 12.3 Metadata ingestion

A seed/import script should:
- Validate file existence.
- Capture file size.
- Extract duration/resolution with `ffprobe` where available.
- Reject unsupported extensions/codecs.
- Register the file under a safe storage key.
- Leave new videos unpublished until checked.

---

## 13. Security and Privacy Requirements

Prototype content may be educational and sensitive. Apply basic security from the start.

- Passwords stored only as strong hashes using a suitable library.
- Authenticated API routes for student data.
- Server-side authorization for every playback request.
- Student identity comes from the authenticated session, not a request body field.
- No directory listing.
- No arbitrary filesystem path endpoints.
- No database port open to student devices.
- Firewall restricts the system to the intended campus network.
- Do not expose OMV administration to student devices.
- No secrets or passwords in Git.
- Logs must not contain passwords, bearer tokens, or other credentials.
- Restrict admin actions to admin accounts.
- Back up database and configuration.
- Keep dependencies updated and pin tested versions.
- Do not expose the prototype to the public internet.
- If using HTTP on an isolated test LAN, document it as a prototype limitation; design a local TLS option for production.
- Use minimal student information in logs and analytics.

### Content protection limitation

Local access control can prevent casual unauthorized access, but it cannot guarantee that a student will not record the screen or copy content from a device that can play it. Stronger content protection is a separate future requirement and may introduce device/platform constraints.

---

## 14. Network Design and Bandwidth Planning

### 14.1 Initial assumptions

Target: 500 concurrent students.

Example planning bitrate: 1.5 Mbps per stream, including an approximate allowance for audio.

- 500 × 1.5 Mbps = 750 Mbps payload.
- Add 25% planning headroom: approximately 938 Mbps.

This is an estimate, not a throughput guarantee. The actual stream bitrate, HTTP overhead, retransmissions, and client behavior must be measured.

### 14.2 Prototype network

- Server connected to a wired switch, not Wi-Fi.
- One AP can be used for the first 2–5 tablet test.
- Use a stable private IP or local DNS.
- Keep WAN disconnected for the internet-independence test.
- Avoid overlapping subnets or guest isolation settings that block client-to-server traffic.
- Confirm Wi-Fi client isolation is disabled for the test SSID if it prevents access to the local server.
- Use a dedicated LMS/student VLAN in a later deployment if appropriate.

### 14.3 Future production planning

For 500 students at 1.5 Mbps each, the video server must deliver approximately 750 Mbps of payload. A 1 GbE link is close to its practical limit after overhead. Evaluate a 2.5 GbE or 10 GbE server connection, switch uplinks, storage throughput, and Wi-Fi capacity.

Do not infer that 11–20 APs will definitely be sufficient. AP models, placement, channel plan, RF interference, uplinks, device capability, and classroom layout all matter. A site survey and real concurrent-device testing are mandatory.

### 14.4 Initial load stages

1. 2–5 physical tablets
2. 10 clients
3. 25 clients
4. 50 clients
5. 100 clients
6. Controlled 500-viewer capacity test

Use both:
- Server-side load generation for HTTP requests/segment delivery.
- Physical wireless clients for real Wi-Fi airtime and roaming behavior.

A server load test alone does not validate Wi-Fi capacity.

---

## 15. Test Plan

### 15.1 Functional tests

| Test ID | Scenario | Expected result |
|---|---|---|
| T-01 | Correct credentials | Login succeeds |
| T-02 | Incorrect credentials | Login rejected without leaking account details |
| T-03 | Inactive student | Access denied |
| T-04 | Browse subjects | Only authorized subjects shown |
| T-05 | Browse chapters | Correct order and published items |
| T-06 | Play MP4 | Video begins |
| T-07 | Seek to middle | Playback resumes at selected position |
| T-08 | Seek near end | Playback continues correctly |
| T-09 | Pause/resume | Works without app crash |
| T-10 | Leave and reopen | Saved position restored |
| T-11 | Unauthorized video ID | Playback authorization denied |
| T-12 | Missing file | Friendly error; server logs failure |
| T-13 | API stopped | App shows recoverable server-unavailable state |
| T-14 | WAN disconnected | Core local playback continues |
| T-15 | Wi-Fi disconnected temporarily | App handles error and can retry/reconnect |
| T-16 | App killed/restarted | Session and progress behavior follows specification |
| T-17 | Two different videos on two tablets | Both stream concurrently |
| T-18 | Progress API retry | No duplicate progress rows |
| T-19 | Admin unpublishes video | New playback authorization denied |
| T-20 | Directory URL requested | No directory listing or unrestricted file access |

### 15.2 Performance tests

Record:
- Playback startup time
- Rebuffer events
- Video errors
- Server CPU and memory
- Network bytes per second
- Disk throughput/latency
- API latency
- Nginx response codes
- Wi-Fi signal, retransmissions, and AP client count if available

Test:
- Different videos at once.
- Same video at once (cache behavior may differ).
- Seeking and pausing.
- 30-minute sustained sessions.
- Repeated starts/stops.
- WAN disconnected.
- AP/client distribution changes.

### 15.3 Load-test limitations

A script requesting the same file can overstate or understate real performance depending on cache behavior and request patterns. Model the player's real Range/segment request patterns. Do not use a load-test result as proof of 500 physical wireless clients.

### 15.4 Test report

For each run, save:
- Date/time
- Server hardware and software versions
- Video file properties and bitrate
- Client device models and counts
- AP model/count and topology
- Network link speeds
- Concurrent session count
- Observed metrics
- Errors and logs
- Pass/fail
- Bottleneck hypothesis
- Next action

---

## 16. Deployment and Configuration Deliverables

The developer must provide a repository containing at least:

```text
campus-lms/
  README.md
  docs/
    PRD.md
    setup-guide.md
    architecture.md
    testing-plan.md
    troubleshooting.md
    backup-restore.md
  backend/
    app/
    tests/
    Dockerfile
    requirements.txt or pyproject.toml
    alembic/
  mobile/
    Flutter project
  deploy/
    compose.yaml
    nginx/
      nginx.conf
      site.conf
    scripts/
      seed_demo_data.py
      inspect_media.py
      backup.sh
      restore.sh
  sample-data/
    README.md
  .env.example
  .gitignore
```

The exact repository layout may differ, but all equivalent items must be present.

### Required documentation
- Fresh install instructions
- Existing OMV integration instructions
- Environment configuration
- Start/stop/restart commands
- How to add a video
- How to create demo users
- How to reset prototype data
- How to run tests
- How to disconnect WAN and test playback
- How to inspect logs
- Backup and restore instructions
- Known limitations
- Upgrade path

Never put real passwords, signing keys, or production data in the repository.

---

## 17. Implementation Milestones

### M0 — Discovery and inventory
**Deliverables**
- Server hardware inventory
- Existing network/subnet record
- Test tablets and Android versions
- Sample video inventory
- Decision: reuse OMV host or prepare fresh host

**Exit criteria:** Team knows which hardware will be used and has a backup plan before making storage changes.

### M1 — Local video proof of concept
**Deliverables**
- Linux/OMV storage folder
- Nginx configured for MP4
- At least three sample videos
- Tablet/browser playback test
- HTTP Range/seek test
- WAN-disconnected playback test

**Exit criteria:** Two devices can play different local videos while public internet is unavailable.

### M2 — Local API and database
**Deliverables**
- FastAPI service
- PostgreSQL schema and migrations
- Demo student accounts
- Seed data
- Health endpoint
- Authentication and course APIs

**Exit criteria:** API tests pass; database is not exposed to student clients.

### M3 — Flutter app
**Deliverables**
- Login
- Home/subject/chapter/video browsing
- Video player
- Error/loading states
- Logout
- Local API base URL configuration

**Exit criteria:** Student completes the core course-to-playback flow on actual tablets.

### M4 — Authorization and progress
**Deliverables**
- Playback authorization
- Secure video URL/access design
- Progress read/write
- Resume playback
- Admin publish/unpublish behavior

**Exit criteria:** Authorized users play assigned videos; unauthorized users are denied; progress persists.

### M5 — Prototype QA and demo
**Deliverables**
- Functional test report
- Internet-independence report
- Performance measurements for 2–5 devices
- Setup guide
- Known-issues list
- Demo recording/screenshots if useful

**Exit criteria:** All mandatory prototype acceptance criteria pass or each failure has a documented blocker and fix plan.

### M6 — Future capacity validation (not part of initial framed prototype)
**Deliverables**
- 10–100 client test results
- Wi-Fi survey
- Server capacity report
- Hardware upgrade recommendation
- 500-viewer test plan

---

## 18. Estimated Timeline

For one developer experienced with the selected stack, estimate:

| Milestone | Estimated duration |
|---|---:|
| M0: Discovery/inventory | 0.5–1 day |
| M1: Local streaming | 1–2 days |
| M2: API/database | 2–4 days |
| M3: Flutter core UI/player | 3–5 days |
| M4: Authorization/progress | 2–3 days |
| M5: QA/documentation | 1–3 days |

Expected framed prototype: approximately **2–3 weeks**, assuming the server hardware is available, no major network issues block local access, and the selected Flutter player works on the target devices. This is a planning estimate, not a fixed commitment.

---

## 19. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Existing NAS/PC underpowered | Playback failures under load | Inventory first; test gradually; separate services if needed |
| Wi-Fi saturation | Buffering despite healthy server | AP survey, wired backhaul, channel planning, staged load tests |
| 1 GbE link saturation | Throughput ceiling at high concurrency | Measure; evaluate 2.5/10 GbE for production |
| Bad video encoding | Slow start, unreadable text, high bandwidth | Inspect source files; use tested encoding profiles |
| Flutter player incompatibility | Seeking or playback issues | Test player options on actual tablets before final selection |
| External service dependency | App fails without WAN | Keep core APIs, DNS, auth, media, and database local |
| Insecure direct media links | Unauthorized viewing | Authorization checks, short-lived URLs/tokens, no directory listing |
| Database exposed on LAN | Data/security risk | Bind DB to internal service network; firewall rules |
| Data loss | Lost course/progress records | Backup database/config; preserve source media |
| Scope creep | Prototype delayed | Enforce non-goals and milestone exit criteria |
| False capacity assumption | Production failure | No 500-viewer claim until measured with documented tests |
| Storage path differences in OMV | Deployment errors | Use configurable `VIDEO_ROOT`, not hard-coded paths |
| Public DNS reliance | Local access fails without WAN | Use local DNS or stable private IP |
| Screen recording/copying | Content leakage | Clearly document limitation; evaluate stronger protection separately |

---

## 20. Future Roadmap (After Prototype)

The following items are planned future improvements. They must not delay the framed prototype unless the initial test reveals they are essential.

### F1 — HLS and adaptive bitrate
- Generate HLS playlists and segments offline.
- Prepare 480p and 720p renditions.
- Verify player support and startup behavior.
- Compare bandwidth, seeking, and buffering with MP4.
- Store renditions efficiently.

### F2 — 500-viewer readiness
- Load-test API and video delivery separately.
- Test 10/25/50/100 clients before a controlled 500-viewer trial.
- Evaluate 2.5/10 GbE server connectivity.
- Review NAS storage throughput and caching.
- Conduct Wi-Fi survey and AP capacity planning.
- Add server/AP monitoring and alerting.
- Consider a dedicated video server and separate NAS.

### F3 — Production admin portal
- Admin/teacher roles.
- Video upload and processing status.
- Bulk import students/courses.
- Publish/unpublish workflows.
- Content assignment by class/section.
- Basic learning analytics.

### F4 — Security and operations
- Local TLS and certificate management.
- Signed/short-lived playback access.
- Rate limiting and session revocation.
- Audit logs for admin actions.
- Tested backups and recovery.
- OS/package patch process.
- Service monitoring and alerts.
- Optional VLAN separation.

### F5 — LMS enhancements
- Teacher dashboards.
- Lesson completion and course progress.
- Search and filters.
- Subtitles and captions.
- Bookmarks and notes.
- Content versioning.
- Optional quiz/assessment module.
- Optional offline downloads, with clear storage and content-control rules.

### F6 — Integration and scale
- Integration with existing school ERP/student records.
- Multiple campuses or server sites if required.
- Optional WAN-connected synchronization, without making local playback dependent on it.
- Central reporting when internet connectivity is available.
- High availability and failover only if operational requirements justify the added cost.

---

## 21. Production Capacity Calculation

At a planning bitrate of 1.5 Mbps per student:

- 100 concurrent streams = 150 Mbps payload.
- 250 concurrent streams = 375 Mbps payload.
- 500 concurrent streams = 750 Mbps payload.
- With 25% planning headroom at 500 viewers = approximately 938 Mbps.

At 2 Mbps per student, 500 viewers require 1,000 Mbps payload before overhead, so a 1 GbE link would be inadequate for that target in practice.

These are network planning calculations, not performance results. Actual file bitrate and network overhead must be measured. Storage I/O, cache behavior, Wi-Fi airtime, switch uplinks, and client devices may be the limiting factors.

A 2.5 GbE or 10 GbE server connection may be appropriate for production, but the final decision must follow testing. More server bandwidth cannot compensate for congested Wi-Fi.

---

## 22. Definition of Done for the Framed Prototype

The framed prototype is done when all of the following are true:

- [ ] Repository is checked in with no secrets.
- [ ] Fresh setup and configuration are documented.
- [ ] Local video directory is configured.
- [ ] Nginx serves MP4 with working HTTP Range/seek behavior.
- [ ] FastAPI and PostgreSQL run locally.
- [ ] Database migrations and demo seed data work.
- [ ] Local student login works.
- [ ] Student can browse assigned subjects, chapters, and videos.
- [ ] Student can request authorized playback.
- [ ] Video streams directly from Nginx, not through the API.
- [ ] Flutter app plays video on at least two actual Android tablets.
- [ ] Seek, pause, resume, and full-screen work.
- [ ] Playback progress persists and resumes.
- [ ] Unpublished/unassigned content is denied.
- [ ] Core playback works with WAN disconnected.
- [ ] Logs are sufficient to diagnose common failures.
- [ ] Functional tests are recorded.
- [ ] A 30-minute multi-tablet test is completed.
- [ ] Known limitations and future work are documented.
- [ ] No claim of 500 concurrent capacity is made without a separate capacity test.

---

## 23. Immediate Developer Task List

Work in this order:

1. **Inventory:** Record available server hardware, current OMV version, storage, NIC speed, Wi-Fi/AP details, and tablet models.
2. **Protect existing data:** Back up any existing OMV data before changing disks or partitions.
3. **Choose host setup:** Reuse OMV if suitable; otherwise prepare a fresh Linux server. Avoid buying hardware until inventory is complete.
4. **Create storage folder:** Make a dedicated LMS media folder and define `VIDEO_ROOT`.
5. **Install/configure Nginx:** Serve three test MP4 files; verify Range requests and seek behavior.
6. **Test LAN-only playback:** Use two tablets and disconnect WAN while keeping LAN/Wi-Fi up.
7. **Build API/database:** Implement migrations, demo users, login, course catalogue, playback authorization, progress, and health checks.
8. **Build Flutter app:** Login → subjects → chapters → video list → player.
9. **Integrate authorization:** Make playback URLs temporary/authorized; avoid arbitrary path exposure.
10. **Implement progress:** Save at sensible intervals and on pause/exit/completion.
11. **Run functional QA:** Complete the test cases in Section 15.
12. **Document the demo:** Record hardware, bitrate, startup times, errors, and resource usage.
13. **Plan next load test:** Increase concurrency gradually; do not skip directly from five tablets to a production claim.

---

## 24. Open Decisions to Resolve During M0

These are intentionally left open until hardware and sample content are inspected:

1. Reuse existing OMV host or prepare a new server.
2. Whether OMV hosts Docker Compose services or serves only storage.
3. Final video player package for Flutter.
4. Local DNS name and subnet.
5. Final authorization mechanism for media URLs while preserving Range requests.
6. Exact video bitrate/encoding profile based on lesson readability.
7. Whether a simple admin web UI is needed for the demo or a seed script is sufficient.
8. Local TLS approach for production.
9. Exact load-testing tools and target metrics.
10. Production server NIC, storage, switch, and AP upgrades based on measured results.

Do not block M1 on decisions that are only needed for production. Use the simplest safe choice that proves local playback.

---

## 25. Final Recommendation

Build the framed prototype as a **local-first system with Flutter, FastAPI, PostgreSQL, Nginx, and OMV-managed video storage**. Start with pre-encoded 720p MP4 files and two to five physical Android tablets. Keep the API out of the video-byte delivery path. Validate authorization, seeking, progress, and operation without public internet before expanding the scope.

After the prototype passes, use measured results—not assumptions—to decide whether to adopt HLS, separate the video server from the NAS, upgrade to 2.5/10 GbE, or redesign the Wi-Fi deployment for 500 concurrent students.

**The prototype proves the architecture. The later load tests prove the capacity.**
