# Test report — 15–16 October 2026 (developer PC, Docker Desktop)

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
