# Troubleshooting (operator checklist)

Start with `deploy/scripts/check_stack.sh` (add `http://<server-ip>[:port]` to test the
address tablets use); it checks each layer in order and exits non-zero on any failure.

## Which layer is failing?

| Symptom | Check | Likely cause / fix |
|---|---|---|
| App: "Can't reach the campus server" | From a laptop on the same SSID: `curl http://<server>/nginx-health` | No answer → network: wrong IP/DNS, tablet on another SSID/VLAN, Wi-Fi client isolation, host firewall, `nginx/allowlist.conf` |
| `/nginx-health` OK, `/health` fails (502) | `docker compose ps`, `docker compose logs api` | API container down or crash-looping (bad `.env` value — the log names it) |
| `/health` OK, `/ready` 503 | `curl http://<server>/ready` | `database: error` → `docker compose logs db`; `media_storage: error` → `VIDEO_ROOT` wrong or disk not mounted |
| Sign-in: "Incorrect username or password" | `lms-admin.sh list-students` | Wrong username; reset with `lms-admin.sh set-password <user>` |
| Sign-in: "Too many attempts" (429) | Nginx log status 429 | 10 tries/min per IP; wait a minute |
| Lesson list empty | `lms-admin.sh tree` | Student not in a class (`assign-class`), chapter unpublished, videos still draft, class/subject inactive |
| "This lesson's video is not available" | API log `media_file_missing` | File moved/renamed/unreadable; `lms-admin.sh check-media` |
| Video error after a long pause | Nginx media log status 410 | Signed URL expired; the app fetches a new one automatically (or on **Try again**) |
| Video 403 | Nginx media log status 403 | `MEDIA_SIGNING_SECRET` differs between API and Nginx: fix `.env`, then `docker compose up -d` (a plain `restart` keeps the old value). Or the file is not readable by Nginx |
| Video 404 | `docker compose logs nginx \| grep '"type":"media"' \| grep '"status":404'` | File missing on disk while DB says it exists; `lms-admin.sh check-media` |
| App: "The campus server is busy" (503 `service_busy`) | API log `admission_timeout` / `db_pool_exhausted` | More simultaneous requests than one worker admits (default 30). Raise `WEB_CONCURRENCY`, or `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` if PostgreSQL has room |
| Slow start / buffering | `inspect_media.py file.mp4` | Not fast-start (re-mux with `-movflags +faststart`), bitrate too high; then Wi-Fi signal/AP load; then server NIC/disk |
| Works with WAN, fails without | Tablet Wi-Fi settings | Uses a public DNS name; "switch to mobile data"/"avoid bad Wi-Fi" enabled; captive portal |
| Progress not saving | API log lines `PUT …/progress` | 401 (session expired — sign in again) or 404 (lesson unpublished) |

## Logs

```bash
cd deploy
docker compose logs --since 30m api            # request lines: request_id, path, status, duration_ms, student_id
docker compose logs --since 30m nginx          # JSON lines: type (api|media|other), uri, status, bytes_sent, range, sid
docker compose logs nginx | grep '"type":"media"' | grep -E '"status":(403|404|410)'   # media problems
docker compose logs api | grep -E ' (ERROR|WARNING) '
```

Media requests are diagnosed from the JSON access lines (uri, status, sid), not from
Nginx's `[error]` log: that log is kept at `crit` level for `/media/` because its lines
would contain still-valid signed URLs.

Follow one request across both: the API's `request_id` equals Nginx's `request_id` for the
proxied call. Follow a student's video session: grep Nginx media lines for `"sid":"<student id>"`
(the same `student_id` the API logs show; `lms-admin.sh list-students` lists them).

Useful API events: `login_failed reason=…`, `login_succeeded`, `playback_authorized`,
`playback_denied`, `media_file_missing`, `ready_check_failed`, `unhandled_exception`.

## Network checks from a tablet

- Open `http://<server>/nginx-health` in the tablet's browser → should show `ok`.
- If not: confirm the tablet's IP is in the same subnet (or routed), the SSID does not
  isolate clients, and the server firewall allows TCP 80 from that subnet.

## Resetting things

| Need | Command |
|---|---|
| Restart one service | `docker compose restart api` (keeps the old environment) |
| Apply `.env` changes | `docker compose up -d` (recreates the services whose settings changed) |
| Sign out a student everywhere | `lms-admin.sh set-password <user>` or `deactivate-student` |
| Clean old sessions | `lms-admin.sh purge-sessions` |
| Wipe all prototype data | Setup guide §12 |
