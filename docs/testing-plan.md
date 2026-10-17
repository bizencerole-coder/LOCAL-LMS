# Testing plan

Three layers:

1. **Automated unit/API tests** — `backend/tests` (pytest, 136 tests: student API, staff
   dashboard, folder sync, migration helpers, CLI, and `test_regressions.py` for defects found
   in review) and `mobile/test` (flutter test, 75 tests). Run on every change.
2. **Stack smoke test** — `deploy/scripts/smoke_test.py` against the running Docker stack
   (real Nginx, PostgreSQL and files; 33 checks, including the dashboard sign-in redirect,
   PDF delivery and the endpoints app 1.0 uses). Run after every deployment, together
   with `deploy/scripts/check_stack.sh`.
3. **End-to-end app test** — `mobile/integration_test/app_flow_test.dart` drives the real
   app on an emulator or tablet against the running stack: sign-in (wrong then right
   password), class-scoped browsing of subjects and modules, playback, seek, speed,
   full-screen, pause, leave and resume within ±10 s, the notes (PDF) viewer, Continue
   Watching, My Learning, sign-out.
4. **Supervised device tests** — two or more physical tablets on the campus Wi-Fi,
   recorded in the report template below, plus a staff member using the dashboard on a
   staff PC (create a module, upload a video and notes, publish, check on a tablet).
   Results so far: [test-report-2026-10-16.md](test-report-2026-10-16.md).

## Coverage of PRD acceptance criteria

| ID | Requirement | Automated | Manual on tablets |
|---|---|---|---|
| AC-01 | Local authentication | `test_auth.py`, smoke | Sign in on each tablet |
| AC-02 | Course browsing | `test_catalog.py`, smoke | Browse seeded content |
| AC-03 | Local playback | `test_playback.py`, smoke (URL host is local) | Play on two tablets |
| AC-04 | Internet independence | — | WAN-disconnect test (setup guide §10) |
| AC-05 | Play/pause, seek, full-screen, speed | — | Player checklist below |
| AC-06 | Resume ±10 s | `progress_reporter_test.dart` (resume rule) | Leave/reopen lesson; compare burned-in timestamp |
| AC-07 | No URL for unassigned/unpublished | `test_playback.py`, smoke `--other-class-username` | — |
| AC-08 | HTTP Range | smoke (HEAD + 3 range requests) | Seek start/middle/end |
| AC-09 | Progress after restart | `test_progress.py`, smoke | Kill app, reopen, resume |
| AC-10 | Diagnostics | — | Find a session in API + Nginx logs by `request_id`/`sid` |
| AC-11 | No public dependency | Code review: no Firebase/analytics/CDN/fonts | WAN test; `adb logcat` shows no external hosts |
| AC-12 | Reproducible setup | — | Second developer follows setup guide from scratch |

## Functional tests (PRD §15.1)

| Test | Automated by | Manual steps |
|---|---|---|
| T-01 correct credentials | `test_login_success…`, smoke | Sign in |
| T-02 incorrect credentials | `test_wrong_password_and_unknown_user…` | Wrong password shows "Incorrect username or password." |
| T-03 inactive student | `test_inactive_student_is_denied` | Sign in as `demo.inactive` |
| T-04 browse subjects | `test_subjects_only_from_own_class…` | `demo.student` sees CS + Maths only |
| T-05 browse chapters | `test_chapters_are_published_and_ordered` | Order matches `sort_order` |
| T-06 play MP4 | smoke (HEAD 200) | Lesson starts |
| T-07 seek to middle | smoke (range middle) | Drag seek bar to middle |
| T-08 seek near end | smoke (range end) | Drag near end; plays to finish, shows Watched |
| T-09 pause/resume | — | Pause 1 min, resume; no crash |
| T-10 leave and reopen | `test_playback_includes_resume_position` | Back out at 2:00; reopen → "Resuming from 1:57" |
| T-11 unauthorized video ID | `test_unpublished_unassigned…`, smoke | — |
| T-12 missing file | `test_missing_file_gives_a_clear_error`, `check-media` | Rename a file; app shows friendly error; API log has `media_file_missing` |
| T-13 API stopped | — | `docker compose stop api`; app shows "Campus server…" with Try again; start API; retry works |
| T-14 WAN disconnected | — | Setup guide §10 |
| T-15 Wi-Fi drop | — | Turn tablet Wi-Fi off 30 s mid-lesson, on again, Try again → continues near same point |
| T-16 app killed/restarted | — | Swipe app away mid-lesson; reopen → still signed in, Continue Watching shows lesson |
| T-17 two videos, two tablets | — | Different lessons concurrently for 30 min |
| T-18 progress retry | `test_retries_do_not_duplicate_rows` | — |
| T-19 unpublish | `test_unpublishing_blocks_new_authorizations` | `lms-admin.sh unpublish-video …`; lesson disappears after refresh |
| T-20 directory URL | smoke (no listing at `/media/`, folder, `/`) | Open `http://<server>/media/` in a browser → 403 |

### Player checklist (AC-05, FR-06)

- [ ] Play/pause (centre button and after controls auto-hide)
- [ ] ±10 s buttons
- [ ] Seek bar drag; time and duration shown
- [ ] Speed 0.5×–2× changes audio/video speed
- [ ] Full-screen: landscape, system bars hidden, back button exits full-screen first
- [ ] Rotating the tablet in normal mode keeps playing
- [ ] Screen does not dim while playing; dims normally when paused
- [ ] Home button pauses playback; returning shows paused video at same point
- [ ] Buffering spinner appears on slow network; error + Try again on failure

## Supervised multi-tablet run (DoD: 30 minutes)

1. Two tablets signed in as `demo.student` and `demo.student2`.
2. Tablet A plays *Limits and Continuity* (32 min); tablet B plays the CS lessons in order.
3. During the run: seek ×5 on each, pause 2 min once, disconnect WAN at minute 10,
   leave and reopen the lesson at minute 20.
4. Record startup time (tap → first frame, stopwatch or screen recording), rebuffer count,
   errors, and server CPU/RAM/network (`docker stats`, `ifstat`/`nload`).

## Performance measurements (PRD §15.2)

| Metric | How |
|---|---|
| Startup time | Stopwatch / screen recording; smoke test prints first-byte times |
| Rebuffer events | Count spinner appearances during the run |
| Server CPU/memory | `docker stats --no-stream` every minute, or `top` |
| Network throughput | `nload <iface>` or `sar -n DEV 5` on the host |
| Disk | `iostat -x 5` |
| API latency | `duration_ms` in API logs |
| Nginx codes / bytes | `docker compose logs nginx \| grep '"type":"media"'` |
| Wi-Fi | AP controller: client count, RSSI, retransmissions |

### Staged load test (server side)

`deploy/scripts/load_test.py` runs the 10 / 25 / 50 / 100-client stages of PRD §14.4
against a running stack. Each simulated student signs in, browses, authorizes a lesson and
streams it like the Android player: an open-ended Range request read at the video's own
bitrate with a 30 s buffer (so the load is sustained, not a download race), a seek about
every 90 s, and a progress save every 20 s. It reports startup time, seek latency, API
p50/p95, aggregate Mbps, rebuffer events (data arriving later than it would be played),
status counts and a `docker stats` snapshot, as a Markdown table for the test report.

```bash
cd deploy
printf '%s\n' "$PW" | scripts/lms-admin.sh create-load-students --count 100 --class "Class 12" --password-stdin
LMS_LOAD_PASSWORD="$PW" python3 scripts/load_test.py --base-url http://192.168.10.10 --clients 10 --duration 120
LMS_LOAD_PASSWORD="$PW" python3 scripts/load_test.py --base-url http://192.168.10.10 --clients 25 --duration 120
# then 50 and 100; run from a wired machine on the LAN, or several machines for 100+
scripts/lms-admin.sh delete-load-students
```

Notes:
- Nginx throttles sign-ins to 10/min (+5 burst) per source address, so from one load
  host a 100-client run spends ~9 minutes signing everyone in (the harness retries 429s
  and starts each client's streaming clock after its own sign-in). Real classes sign in
  from one address per tablet and are not affected.
- Run it on a machine other than the server where possible: the generator itself uses
  CPU, and the server's NIC is part of what is being measured.
- It does **not** validate Wi-Fi capacity (PRD §15.3): repeat each stage with physical
  tablets on the real access points. A server-side pass is necessary, not sufficient.
- Exit code 1 if any 5xx was returned. 503 `service_busy` is counted separately: a few
  under a burst are expected and retried; many mean the API needs more workers.

## Test report template

Copy for each run into `reports/` (git-ignored) or the project tracker.

```markdown
# Test run — YYYY-MM-DD HH:MM

- Tester(s):
- Server: CPU / RAM / disk / NIC speed / OS / Docker version / git commit
- Video files: names, duration, bitrate (inspect_media.py output)
- Clients: device models, Android versions, count
- Network: AP model/count, SSID, band/channel, switch & uplink speeds, WAN state
- Concurrent sessions:

| Test | Result | Notes |
|---|---|---|
| T-01 … T-20 | pass/fail | |

- Startup times (s):
- Rebuffer events:
- Errors (with request_id / sid):
- Server peak CPU / RAM / network:
- Pass/fail overall:
- Bottleneck hypothesis:
- Next action:
```
