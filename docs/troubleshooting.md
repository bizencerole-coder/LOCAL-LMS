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
| Sign-in: "Too many wrong passwords for this account. Try again in N minutes." | API log `login_failed` `reason=locked` | 5 wrong passwords within 10 minutes lock that account for 10 minutes (`LOGIN_MAX_FAILURES`, `LOGIN_LOCK_SECONDS`). Wait, or a teacher sets a new password (dashboard *Students* or `lms-admin.sh set-password`), which lifts the lock |
| Sign-in: "Too many attempts. Please wait a minute" (429), many students at the start of class | Nginx access log: do all tablets show the same `remote_addr`? | Nginx allows 10 sign-ins a minute per address. Tablets behind a router that translates addresses (NAT) share one: `scripts/set_network.sh --login-gateway <that address>` |
| Subject/module list empty, or an item missing | Dashboard: the student's page (class), then the module page | Student not in a class, or in another batch's class; batch, class or subject inactive; module hidden; item still a draft or archived |
| A file copied to the share does not appear in the app | Dashboard *Folder sync* (or `tail /srv/backups/lms/sync.log`) | The sync runs every 5 minutes (*Sync now* to run it at once). `skip … not a batch`: the top folder must be a batch folder (shown on the batch's page). Under another class's folder (`batch-2026-27/class11/…` is only shown to Class 11 students). Name with spaces or other characters (`skip`): rename it. Wrong depth (`<batch>/<class>/<subject>/[<module>/]<file>`). `FAIL`/`WARNING`: fix the file (setup guide §7.2). New items from the share are published only when the file passes the check |
| An item shows but will not open after files were moved or deleted | `lms-admin.sh check-media`; the item's page in the dashboard | The next sync re-files moved items and archives deleted ones; a `FAIL` that persists means the file is really gone or unreadable |
| "This item's file is not available" | API log `media_file_missing` | File moved/renamed/unreadable; `lms-admin.sh check-media` |
| Dashboard: "Incorrect username or password" | `lms-admin.sh list-staff` | No account or wrong username; `lms-admin.sh create-staff …` or `set-staff-password <user>` (an administrator can also reset it under *Staff*). The account may be inactive |
| Dashboard: "The server cannot change files in …" / uploads fail with that message | `stat -c '%u %g' "$VIDEO_ROOT"` and the named folder | The API does not run as the folder's owner: set `LMS_CONTENT_UID`/`LMS_CONTENT_GID` in `.env` to that owner, `docker compose up -d api`. A folder created by another account (e.g. root) needs `chown -R` to the owner |
| Dashboard: "This form has expired" | — | The page was open across a sign-out or from another tab's session; reload the page and try again |
| Upload: "larger than the upload limit" / "disk is nearly full" | `.env` `UPLOAD_MAX_BYTES`; `df -h "$VIDEO_ROOT"` | Raise the limit (Nginx allows up to 8 GiB), or free space: at least 1 GB must stay free. Very large videos can also be copied into the share |
| Upload: "not a PDF", "Cannot read … as an MP4 video", "not fast-start" | `python3 scripts/inspect_media.py file.mp4` | The file is not what its name says, or the video needs re-encoding/re-muxing (setup guide §7, `sample-data/README.md`). Items with problems stay drafts; *Publish anyway* is on the item's page |
| Tablet: notes or an image "could not be opened" / "link expired" | Nginx media log for that file | *Try again* opens it with a fresh link. A damaged PDF opens nowhere: check it on a PC. Notes and images over 100 MB are refused on the tablet (split the PDF or lower the image resolution) |
| Video error after a long pause | Nginx media log status 410 | Signed URL expired; the app fetches a new one automatically (or on **Try again**) |
| Video 403 | Nginx media log status 403 | `MEDIA_SIGNING_SECRET` differs between API and Nginx: fix `.env`, then `docker compose up -d` (a plain `restart` keeps the old value). Or the file is not readable by Nginx |
| Video 404 | `docker compose logs nginx \| grep '"type":"media"' \| grep '"status":404'` | File missing on disk while DB says it exists; `lms-admin.sh check-media` |
| Windows: "cannot access `\\server\campus-lms`" (0x80070043) | On the server: `systemctl is-active smbd` | Samba not running. In OMV, *Services → SMB/CIFS → Settings → Enabled* must be ticked and applied; the save is refused if the hostname is longer than 15 characters (*Network → General*, e.g. `lms`). "Access is denied" instead means use the `lmsadmin` credentials |
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
