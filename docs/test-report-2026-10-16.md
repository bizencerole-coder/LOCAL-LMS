# Test report — 15–17 October 2026 (developer PC, Docker Desktop, OMV host)

**Scope:** verification of the framed prototype software on the development machine, before
any on-site hardware exists. This covers everything that can be tested without the campus
network and physical tablets. It is **not** the PRD §4.1 acceptance run, which needs two
real tablets on the campus Wi-Fi with the WAN unplugged (see "Still open" below).

## Environment

| Item | Value |
|---|---|
| Host | Windows 11 Pro, 12 CPUs, 31.6 GB RAM, Docker Desktop 4.78 (engine 29.5.3, WSL 2), Compose v5.1.4 |
| Stack | `deploy/compose.yaml`: postgres:17-alpine, campus-lms-api (Python 3.12, FastAPI 0.143), nginx:1.28-alpine, published on `127.0.0.1:8080` |
| Media | 5 generated MP4s (H.264 High/AAC, 1280×720, ~1.24 Mbps, fast-start): 3 + 8 + 2 (draft) + 32 + 3 minutes, in `D:\Local LMS\campus-lms-media\videos` |
| Client | Android emulator `CampusLMS_Tablet` (Pixel Tablet, Android 15 / API 35, x86_64), reaching the host at `10.0.2.2:8080` |
| Code | working tree of 16 Oct 2026 (uncommitted) |

## Results

| Layer | Test | Result |
|---|---|---|
| Backend | `pytest` (SQLite): auth, catalogue, playback signing, progress upsert, media keys, MP4 inspector, admin CLI, health, 17 regression tests | **95 passed** |
| App | `flutter test`: API client, server-address validation, progress reporter (flush, sticky completion), formatting, lesson tile | **26 passed**; `flutter analyze` clean |
| Stack | `deploy/scripts/smoke_test.py` (real Nginx/API/PostgreSQL/files): login, catalogue, signed playback, HEAD + Range 206 at start/middle/end, unsigned/tampered/extended-expiry/non-GET denied, no directory listing, path traversal, progress save/read, cross-class denial, logout | **29/29** |
| Stack | `deploy/scripts/check_stack.sh` (operator checklist) | ALL CHECKS PASSED, exit 0 |
| Stack | Live re-check after fixes: forwarded-IP spoofing ignored, `no-store` on API, media headers not duplicated on 416, POST/OPTIONS on media → 405, signed directory → 404, relative redirects, `/docs` served without internet, malformed `Host` → 400, strict progress JSON, **150 concurrent progress saves: 150 × 200 in 2.1 s** (before the fix: 150 × 504 after 30 s) | 20/20 |
| Stack | `backup.sh` (path with spaces, retention), `restore.sh` (good dump: data intact, services back; corrupt dump: live database untouched, services back) | pass |
| App on emulator | `integration_test/app_flow_test.dart`: wrong password rejected → sign-in → only own class visible, draft lesson hidden → play Lesson 2 → seek to 4:00 → speed 1.5× → full-screen and back → pause → leave → "Resume at" shown → reopen resumes within ±10 s → Continue Watching and My Learning → sign-out | **passed** (40 s run, resumed 1 s from the paused position) |
| Logs | Full-stack log scan: no passwords, tokens, signing secret or URL signatures in any container log; request IDs match between Nginx and API lines; media lines carry `sid` | pass |

Measured on this machine (loopback, not Wi-Fi): login ≈ 80 ms, playback authorization ≈ 25 ms,
first byte of a Range request ≈ 8 ms, `GET /subjects` p50 18 ms sequential and ≈ 80–100 req/s
with 2 API workers.

### Staged load test (`deploy/scripts/load_test.py`, loopback, generator on the same PC)

| Stage | Streaming / client | Sustained media rate | Startup p50 / p95 | Seek first byte p50 / p95 | Rebuffers | 5xx / 503 | Server at full load |
|---|---|---|---|---|---|---|---|
| 10 clients | 60 s | 12.4 Mbps (1.24 per client + 30 s buffer each) | 55 / 94 ms | 16 / 20 ms | 0 | 0 / 0 | API 0.7 % CPU, Nginx 0.5 %, DB 0 % |
| 25 clients | 120 s | 30.9 Mbps | 59 / 84 ms | 19 / 44 ms | 0 | 0 / 0 | API 12 % CPU (216 MB), Nginx 9 % (87 MB), DB 3 % |

API latency at 25 clients: login p50 81 ms, catalogue 25–27 ms, playback 24 ms, progress
38 ms (p95 ≤ 56 ms). The 25-client run saw 151 × HTTP 429 on sign-in: the per-IP login
throttle (10/min + 5) applied to the single load host; the harness retried and every
client signed in. These runs exercise the API, Nginx and disk only — the 50- and 100-client
stages and all Wi-Fi measurements must be done on the campus network (PRD §14.4, §15.3).

## First run on the OMV host and a physical tablet (16 Oct 2026, office LAN)

Host: the old office PC from [m0-inventory.md](m0-inventory.md) (Core i3-2100, 7.7 GB, one 1 TB
HDD), OpenMediaVault 8.5 on Debian 13, installed with `deploy/install.sh` (first real run of the
script; it also exposed and fixed two host issues: OMV's own web UI held port 80 and was moved
to 8081, and Nginx had to be restarted once because it started before Docker DNS could resolve
`api`). Tablet: realme Pad 2 (RMP2204, Android 14) on Wi-Fi `OFFIZE-NET`, 172.18.2.46/23;
server on 172.18.1.169/24; the segments are routed through 172.18.1.1.

| Test | Result |
|---|---|
| `scripts/check_stack.sh` on the host | ALL CHECKS PASSED (5 videos, DB, storage, HTTP) |
| `smoke_test.py` from a Windows laptop on the LAN against `http://172.18.1.169` | **29/29** — login 144 ms, playback authorization 40 ms, first byte of Range requests 15–27 ms |
| App on the tablet: sign-in, browse, play Lesson 1 | **works** — streams from the OMV host; wrong-password error shown correctly first |
| Resume across devices (AC-06/AC-09) | **works** — smoke test saved 42 s for `demo.student`; the tablet opened the lesson at 0:39 ("Resuming from 0:39") |
| AC-11 (no public dependency) | app start, sign-in and playback used only `172.18.1.169` (Nginx log) |
| Player checklist (seek, speed, full-screen, pause, rotate), T-14 WAN unplugged, T-17 two tablets, 30-minute run | **not yet run** — next on site |
| Content workflow: a lesson copied into the SMB share (`class11/physics/49-….mp4`) | **registered and published by the 5-minute cron sync** without any command; it landed under Class 11 because of its folder, so `demo.student` (Class 12) could not see it. Moved to `class12/computer-science/01-python-basics/04-python-tutorial.mp4`: the sync re-filed the same lesson as "Python Tutorial", lesson 4; a Class 12 account saw and played it through the API, and the realme tablet showed it under Python Basics for `demo.student` |
| Share ↔ app structure: the 5 demo files moved into `class/subject/NN-chapter/NN-lesson.mp4` on the server, then `sync-videos` | **5 moved in place** — same IDs, status and progress; `check-media` 6/6 OK; signed playback of a moved lesson 200 / Range 206 / unsigned 403; rehearsed first on the local stack (smoke 27/27 afterwards) |

Network finding: Nginx logs every client as `172.18.1.1` (the router NATs the tablet segment onto
the server segment). Consequences for the pilot: the per-IP login throttle (10/min + 5) is shared
by *all* tablets behind that router, so a class signing in together would see 429s, and the
allowlist/logs cannot tell tablets apart. Fix for the campus deployment: put the LMS host on the
same network as the tablets, or have the router route (not NAT) between the segments. Until then,
raise the login limit in `site.conf.template` if more than ~10 tablets sign in within a minute.

## Staff dashboard and the batch › module content model (17 Oct 2026, developer PC)

Commit `bd6450a`. Tested on the local Docker stack, which still held the data of 15–16 Oct
(2 classes, 29 students with progress), so the upgrade itself was exercised on real data.

| Test | Result |
|---|---|
| Backend tests (pytest) | **136 passed**: student API, dashboard (sign-in, CSRF and Origin checks, uploads, moves, deletes, permissions, students, CSV import, staff), folder sync, CLI |
| App tests | `flutter analyze` clean; **75** unit and widget tests passed |
| Upgrade of the local database (migration 0002) | Batch *Batch 2026-27* created with both classes; every class, subject, module, item, student and progress row kept its ID; storage keys prefixed; the API moved the folders into `batch-2026-27/` on start; `check-media` 5/5 OK |
| `smoke_test.py` | **33/33**, now including the dashboard sign-in redirect, PDF delivery (`application/pdf`) and the endpoints app 1.0 still uses |
| Dashboard in a browser (local stack) | Sign-in, overview, content tree and module page render with live data; dropping a PDF and a PNG on the upload area uploads both through Nginx and publishes them; a `.docx` is refused in the browser; image preview through a signed media URL |
| Dashboard file operations (scripted, local stack) | 27 MB video uploaded through Nginx in 0.4 s; notes moved to another subject's module (file and title file moved, progress kept); delete moved the file to `.trash`; a folder sync afterwards found nothing to change |
| App end-to-end on the emulator | Sign-in, subjects → modules → videos with resume, notes viewer (*Page 1 of 3*), My Learning, sign-out: **passed** (42 s), before and after the visual refresh |
| `deploy/scripts/upgrade.sh --no-pull` | Backup, settings kept, rebuild, all containers healthy, `check_stack.sh` ALL PASSED |

Found and fixed during these tests:

- The pages' Content-Security-Policy blocked the inline style that hid the icon sheet (a grey
  band at the top of every page): now hidden with a stylesheet class.
- Upload errors in the API's standard format showed as "[object Object]" in the upload list.
- Renaming whole folders was refused on the Windows bind mount during the folder move: the
  move now goes file by file, which works everywhere.
- The API must run as the owner of the content folder, or uploads fail with a server error:
  `LMS_CONTENT_UID`/`LMS_CONTENT_GID` (set by `install.sh` and `upgrade.sh`), a clear message
  when a write is refused, and a warning on the dashboard naming the folder.
- A folder sync starting during the upgrade could have archived items whose files were not
  moved yet: the folder move now holds the lock the sync waits for.
- The cron-pause pattern in `upgrade.sh` could never match (the sed delimiter was also the
  regex alternation); verified with a pause/resume round trip.

### Upgrade of the campus server (17 Oct 2026, ~09:57)

After the server was switched on, `git pull` (to `d54df17`) and
`deploy/scripts/upgrade.sh --no-pull --share-path '\\172.18.1.169\campus-lms\videos'` as lmsadmin:

| Step / check | Result |
|---|---|
| Backup, sync paused, settings | Database and configuration backed up; cron line paused and put back; `.env` gained `LMS_CONTENT_UID=1000`, `LMS_CONTENT_GID=100` (owner of the content folder, lmsadmin:users) and `CONTENT_SHARE_PATH` |
| Rebuild and migration | New image built on the host; migration 0002 ran; `class11/` and `class12/` moved into `batch-2026-27/`; all containers healthy; `check_stack.sh` ALL PASSED; **UPGRADE COMPLETE** |
| Data kept | Same IDs for every class, subject, module and item (including the user's *Python Tutorial*); 4 students; `check-media` 6/6 OK |
| API as the folder owner | runs as uid 1000 / gid 100 and can write in `batch-2026-27/` |
| Signed media links (generated inside the API container) | video `video/mp4`, notes `application/pdf`, image `image/png`: HEAD 200, Range 206, unsigned 403 |
| Dashboard | `/admin/login` 200, `/admin/` and `/` redirect to the sign-in |
| Demo notes and image | generated on the host and registered by the seed (published) |
| First administrator | `admin` created; the user typed the password in a terminal tab |
| Tablet | realme Pad 2 updated to app 1.1.0 with `adb install -r`; yesterday's 8-hour sign-in had expired, so the user signed in again as `demo.student`. Home shows *Batch 2026-27 · Class 12*, Continue watching with yesterday's resume points kept (*Python Tutorial* 0:11, *Lesson 1* 0:20), subjects with counts and progress; Python Basics lists the three videos and the notes; the notes open as PDF pages (*Page 1 of 3*) from the campus server |

### Dashboard buttons refused (17 Oct 2026, reported by the user)

Deleting an item on the campus dashboard answered *Not allowed: This form has expired*.
Cause: the templates imported the form helpers from `_macros.html` without the template
context, so the hidden `csrf_token` in every form was empty and every button (save, publish,
delete, sign out…) was refused. Uploads still worked because the upload script sends the
token from the page's `<meta>` tag, and the tests and the scripted checks above posted that
same token instead of the one in the form, so they passed.

Fix (`b59fb10`): every template imports the helpers `with context`; new tests submit the
hidden fields each form actually renders (every form on 13 pages carries the page's token;
publish, delete and sign-out succeed with them) and fail on the old templates. Backend tests
**138 passed**; Publish and Unpublish clicked in the browser on the local stack.

Deployed to the campus server at ~10:10 with `git pull` and `upgrade.sh --no-pull`:
**UPGRADE COMPLETE**, all containers healthy; a page rendered inside the server's API
container carries the token in both of its forms; the API (uid 1000 / gid 100, owner of the
content folder) can write all 10 content folders, so a delete can move the file into
`.trash`. Pages opened before the upgrade still hold the empty token and must be reloaded.

## Review findings and fixes

A multi-agent code review (6 reviewers + adversarial verification) and a live probe of the
running stack (6 probers) produced 85 findings; 56 were confirmed as real defects, the rest
were refuted as intended prototype behaviour or duplicates. All confirmed defects are fixed:

**High**
- API worker deadlock under bursts of ~70+ requests (threads waiting for pool connections
  while connection holders waited for threads): added an ASGI admission gate per worker,
  5 s pool timeout and a 503 `service_busy` answer with `Retry-After`.

**Medium**
- Player: system bars not restored after full screen on Android 7–14; lesson could start
  playing after the tablet was locked while loading; lists reloaded before the final
  progress save; a failed completion save was never retried; progress not saved after a
  decoder error; a possible leaked timer when leaving during the resume seek.
- App: false "server not reachable" after a session expired; server-address dialog
  accepted unusable addresses and could hang on "Testing…"; sign-in failed silently on
  keystore errors; cards overflowed at large font sizes.
- Nginx: Swagger `/docs` loaded from a CDN (blank on an offline LAN) → assets vendored;
  signed URLs could appear in the error log → `crit`-only error log for `/media/`, 405 via
  `return`, directories answer 404; `$lms_log_type` undefined for early-rejected requests →
  `map`; client-spoofable `X-Forwarded-For`; cacheable error pages; absolute redirects
  dropping the published port.
- Scripts/docs: `restore.sh` could delete the dump it was restoring and leave the stack
  down; `check_stack.sh` ignored `LMS_HTTP_PORT` and always exited 0; `lms-admin.sh`
  broke `--password-stdin` pipes and Git Bash paths; `backup.sh` retention failed on paths
  with spaces; cron example could not run as a non-root user; ufw advice did not apply
  to Docker-published ports; several command examples failed from the documented
  directory.

**Low (selection)**
- NUL in a username caused a 500 on PostgreSQL; 500 responses lost the request ID; text
  log values could forge fields; MP4 inspector crashed on malformed headers and misread
  QuickTime files; seed re-runs failed on untrimmed names; database data errors were raw
  tracebacks in the CLI; smoke test failed at random 1 run in 64 and crashed when the
  server was down; progress accepted booleans/strings as numbers; a malformed `Host`
  header leaked the internal API address into playback URLs.

Container hardening added at the same time: internal database network, `cap_drop`,
`no-new-privileges`, read-only API image.

Found on the tablet later the same day: the player's "Resuming from …" notice stayed at the
bottom of every screen after leaving the player, because it was shown through the app-wide
messenger. It is now shown by the player's own messenger (gone when the player closes) and
limited to six seconds; app version 1.0.1.

Refuted (intentional, documented instead): last-writer-wins for concurrent saves from two
devices; completion counts the position reached (seeking counts); case-insensitive media
paths on the Windows bind mount; signed-secret holders can tell directories from files;
Nginx-generated HTML error pages; secrets visible through `docker inspect`.

## Still open (needs the campus site)

| PRD item | Status |
|---|---|
| M0 inventory (server, network, tablets, sample content) | not started — template in `docs/m0-inventory.md` |
| AC-04 / T-14 WAN-disconnected playback | untested (needs the campus router) |
| AC-05, AC-06 on real tablets; T-15 Wi-Fi drop; T-17 two tablets concurrently | untested on physical devices; passed on the emulator |
| 30-minute multi-tablet run, startup times and rebuffer counts over Wi-Fi | not run |
| Load stages 50 and 100 clients (server side), then with physical tablets | not run; harness ready (`load_test.py`), 10 and 25 passed on loopback |
| Player package choice (`video_player`/ExoPlayer) on the target tablets | provisional until tried on the real models |
| Android licences on the dev PC (`flutter doctor --android-licenses`) | not accepted; builds still work |

Known limitations are listed in `docs/architecture.md`. No claim is made about 500
concurrent viewers.
