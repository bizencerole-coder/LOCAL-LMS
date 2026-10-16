# Setup guide

This brings up the prototype on one Linux host (fresh server, or an existing
OpenMediaVault machine) and connects Android tablets over the campus Wi-Fi.

Before changing any existing machine, complete the inventory in
[m0-inventory.md](m0-inventory.md) and **back up existing data**. Do not reformat or
repurpose a disk without the owner's approval (PRD §11.1).

## 1. Requirements

| Item | Minimum for the 2–5 tablet prototype |
|---|---|
| Host | 64-bit Linux (Debian 12/13, Ubuntu 24.04, or OMV 7/8), 4 GB RAM, wired Ethernet |
| Software | Docker Engine 24+ with the Compose plugin, `curl`, Python 3.10+ (for scripts) |
| Network | Fixed private IP for the host (example `192.168.10.10`) or local DNS name |
| Tablets | Android 7.0+ (API 24), on an SSID that can reach the host |

## Quick install (script)

`deploy/install.sh` runs sections 2–6 and 8 below as one command on a fresh Debian 12/13,
Ubuntu 24.04 or OMV 7/8 host. Run it as the sudo-capable operator account, from the checkout:

```bash
deploy/install.sh --dry-run                                    # show what would be done; changes nothing
deploy/install.sh --allow 192.168.10.0/24 --firewall --demo    # fresh host: Docker, folders, .env, access control, stack, demo data
deploy/install.sh --video-root /srv/dev-disk-by-uuid-XXXX/campus-lms/videos \
    --media-base-url http://lms.campus.lan --allow 192.168.10.0/24    # OMV shared folder, local DNS name
```

It checks the prerequisites (64-bit Linux, `curl`, Python 3.10+, free disk, sudo), installs
Docker with the official script after asking, creates `VIDEO_ROOT` and the backup folder
(folders only: it never formats, partitions or mounts a disk, and refuses an OMV
`/srv/dev-disk-by-*` path whose disk is not mounted), writes `deploy/.env` with generated
secrets (mode 600) and the host's LAN address as `MEDIA_BASE_URL`, narrows
`nginx/allowlist.conf` to the `--allow` subnets, adds the `DOCKER-USER` rule with
`--firewall` (re-applied after every boot and Docker restart by the systemd unit
`campus-lms-firewall.service`), starts the stack, waits until all three services are healthy,
optionally seeds the demo content, and ends with `scripts/check_stack.sh` and the next steps.
Every step is skipped when it is already done, so the script can be re-run; an existing `.env`
or a hand-edited allowlist is replaced only with `--force` (a copy is kept in `deploy/backups/`).
`deploy/install.sh --help` lists all options. The sections below remain the reference for what
the script does and for doing it by hand.

## 2. Fresh Linux host

```bash
# Docker Engine + Compose plugin (official convenience script; review it first)
curl -fsSL https://get.docker.com -o get-docker.sh && less get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker "$USER"      # log out and back in

# Video directory (owned by the content admin account, readable by containers)
sudo mkdir -p /srv/campus-lms/videos
sudo chown "$USER": /srv/campus-lms/videos
```

Give the host a static address (or a DHCP reservation) and, if possible, a local DNS
record such as `lms.campus.lan`. Do not rely on public DNS (FR-10).

## 3. Existing OpenMediaVault host

0. Give the machine a hostname of **15 characters or fewer** (*Network → General*, e.g. `lms`):
   Samba refuses to start with a longer one, and the OMV installer's default
   (`openmediavaultlms`) is 17.
1. In OMV, create a shared folder for the LMS media, e.g. `campus-lms` on the data disk.
   Note its absolute path: *Storage → Shared Folders* shows it as
   `/srv/dev-disk-by-uuid-<UUID>/campus-lms`. Create `videos/` inside it.
2. Give write access only to the content-admin user (SMB/NFS share for uploading).
   The containers mount the folder **read-only**.
3. Install Docker using the **openmediavault-compose** plugin (OMV-Extras) or Docker
   Engine as above. Do not install a second container manager alongside an existing one.
4. Keep OMV's web UI on its own port and do not expose it to student networks.
5. Set `VIDEO_ROOT` (step 4) to the shared folder's absolute `.../campus-lms/videos` path.
   Never hard-code the disk UUID in application code; it lives only in `deploy/.env`.

If the compose plugin cannot run this file as-is, run the three services natively
(PostgreSQL 17, Python 3.12 + `backend/requirements.txt`, Nginx with
`deploy/nginx/*`) and document the differences.

## 4. Configure

```bash
git clone <repository> campus-lms && cd campus-lms/deploy
cp .env.example .env
chmod 600 .env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # run twice: DB password, signing secret
nano .env
```

| Variable | Meaning |
|---|---|
| `POSTGRES_PASSWORD` | Database password (letters, digits, `-`, `_` only) |
| `MEDIA_SIGNING_SECRET` | Shared by API and Nginx to sign/verify playback URLs (≥32 chars, same charset) |
| `VIDEO_ROOT` | **Host** path of the MP4 library; mounted read-only at `/srv/campus-lms/videos` |
| `MEDIA_BASE_URL` | Fixed base for playback URLs (`http://lms.campus.lan`), recommended on a LAN; empty = the address each tablet typed |
| `PLAYBACK_URL_TTL_SECONDS` | Signed URL lifetime (default 7200). When a URL expires mid-lesson the app fetches a new one and continues |
| `SESSION_TTL_SECONDS` | Sign-in lifetime (default 28800 = 8 h) |
| `COMPLETION_THRESHOLD` | A lesson is complete once the playback position reaches this fraction of its length (default 0.9; seeking counts; 0 = only when the video plays to the end) |
| `LMS_HTTP_BIND` / `LMS_HTTP_PORT` | Where Nginx listens. Binding to the LAN IP keeps other interfaces closed, but does not filter by source |
| `LOG_FORMAT` | `text` or `json` for API logs |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_ADMISSION_LIMIT` | Capacity per API worker (see `.env.example`); leave the defaults for the prototype |

**Restrict who can reach the server.** Two layers:

1. `deploy/nginx/allowlist.conf`: narrow it to the real student/staff subnets (keep the
   Docker `172.16.0.0/12` line). This is the in-stack control and works because Docker
   preserves the client's source address. Apply with `docker compose restart nginx`.
2. Host firewall: Docker-published ports **bypass** plain `ufw`/`INPUT` rules and OMV's
   firewall page. Filter in the `DOCKER-USER` chain instead, for example:

   ```bash
   sudo iptables -I DOCKER-USER -i eth0 -p tcp -m conntrack --ctorigdstport 80 --ctdir ORIGINAL \
       ! -s 192.168.10.0/24 -j DROP      # repeat with each allowed subnet before the DROP, or use an ipset
   sudo apt install iptables-persistent   # keeps the rule across reboots
   ```

   `deploy/install.sh --firewall --allow <subnet> ...` writes the same rules to
   `/usr/local/sbin/campus-lms-firewall` and a systemd unit that re-applies them after each
   boot and Docker restart, which also works on OMV without `iptables-persistent`.

PostgreSQL and the API publish no ports; the database is on an internal Docker network
that only the API can reach.

## 5. Start, stop, restart

```bash
cd deploy
docker compose up -d --build        # first start; migrations run automatically
docker compose ps                   # all three services should be "healthy"
docker compose logs -f api nginx    # follow logs
docker compose restart nginx        # after editing nginx config or allowlist
docker compose stop                 # stop (data kept)
docker compose start
docker compose down                 # remove containers (data volume kept)
```

Services restart automatically after a reboot (`restart: unless-stopped`) as long as the
Docker service is enabled (`sudo systemctl enable docker`).

## 6. Demo content and users

```bash
scripts/make_test_videos.sh /srv/campus-lms/videos            # 5 files, incl. a 32-min lesson (~9 min to encode)
scripts/make_test_videos.sh /srv/campus-lms/videos --short    # quicker: long lesson cut to 5 min
scripts/seed_demo_data.sh                                     # prompts for the demo password
```

The seed (from `backend/seed/demo_catalog.json`) creates:

| Username | Class | Purpose |
|---|---|---|
| `demo.student`, `demo.student2` | Class 12 | Main demo accounts (two tablets) |
| `demo.class11` | Class 11 | Must not see Class 12 content (AC-07) |
| `demo.inactive` | Class 12 | Inactive account; sign-in is refused (T-03) |

All demo accounts share the password you type; it is never stored in the repository.
Re-running the seed is safe: existing records are left alone. To script it, pipe the
password: `printf '%s\n' "$PW" | scripts/seed_demo_data.sh --password-stdin`.

## 7. Adding lessons: the folder layout and `sync-videos`

The catalogue the app shows (class → subject → chapter → lesson) can be built straight
from the folders under `VIDEO_ROOT`. Teachers copy files; the server registers them.

### 7.1 Folder layout

```text
VIDEO_ROOT/
  class12/                         → class "Class 12"
    computer-science/              → subject "Computer Science"
      01-python-basics/            → chapter "Python Basics", order 1
        01-variables-and-types.mp4 → lesson "Variables And Types", order 1
        02-python-functions.mp4    → lesson "Python Functions", order 2
        02-python-functions.txt    → optional: first line = title, rest = description
      title.txt                    → optional: overrides the subject's display name
    mathematics/
      quick-revision.mp4           → no chapter folder: goes into a chapter called "Lessons"
```

Rules:
- Names may contain letters, digits, `.`, `-` and `_` only — **no spaces** and nothing else.
  Use `title.txt` (in a class, subject or chapter folder) or `<lesson>.txt` (next to a file)
  for the names students should see, e.g. `Class 12 – Science` or `Lesson 2: Functions`.
- A leading number and dash (`01-`, `02-`) sets the order and is removed from the name.
  `-` and `_` become spaces, words are capitalised, and `class12` becomes `Class 12`.
- Exactly three or four levels: `class/subject/lesson.mp4` or `class/subject/chapter/lesson.mp4`.
- Files must be H.264 + AAC MP4 with fast-start (PRD §12). Check before copying with
  `python3 scripts/inspect_media.py lesson.mp4`; a file with problems is registered but
  stays a draft until fixed.
- Student access follows the class name: `scripts/lms-admin.sh assign-class <username> "Class 12"`.

### 7.2 Copying files to the server

From Windows: open `\\172.18.1.169\campus-lms` (OMV SMB share; sign in as `lmsadmin`) and
copy into `videos\class12\computer-science\...`. From Linux/macOS: `scp` or an SMB mount.
The share is for the content administrator only — keep it off the student Wi-Fi (PRD §11.2).

### 7.3 Registering them

```bash
scripts/lms-admin.sh sync-videos             # registers new files as drafts; existing ones are untouched
scripts/lms-admin.sh tree                    # review names, order and status
scripts/lms-admin.sh publish-video class12/computer-science/01-python-basics/02-python-functions.mp4
scripts/lms-admin.sh sync-videos --publish   # or: publish every new file that passes the check
scripts/lms-admin.sh sync-videos --archive-missing   # also hide lessons whose files were removed
```

To make new files appear in the app on their own, run the sync every few minutes from
cron (or *System → Scheduled Tasks* in OMV, as `lmsadmin`):

```cron
*/5 * * * * cd /home/lmsadmin/campus-lms/deploy && scripts/lms-admin.sh sync-videos --publish >> /srv/backups/lms/sync.log 2>&1
```

Copy a lesson's files completely before the next run (or copy to a temporary folder
outside `videos/` and move it in): a half-copied file is registered with the wrong size and
would need `check-media --update` afterwards.

For titles or placements the folder rules cannot express, register by hand instead:
`add-video --chapter "Class 12/Computer Science/Python Basics" --storage-key <key> --title "..." --sort N`.

Other admin commands (`scripts/lms-admin.sh --help`): `create-class`, `create-subject`,
`create-chapter [--publish]`, `publish-chapter`, `unpublish-chapter`, `create-student`,
`set-password`, `assign-class`, `activate-student`, `deactivate-student`,
`list-students`, `create-load-students` / `delete-load-students` (for §14),
`scan-videos`, `add-video`, `unpublish-video`, `archive-video`, `check-media [--update]`,
`purge-sessions`, `seed-demo`. Passwords are always prompted for (or read with
`--password-stdin`), never passed as arguments.

Example — create a student:

```bash
scripts/lms-admin.sh create-student --code S12-014 --username anu.k --name "Anu K" --class "Class 12"
```

## 8. Verify the stack

```bash
scripts/check_stack.sh                         # the address Nginx publishes; exit code 1 on any failure
scripts/check_stack.sh http://192.168.10.10    # the address tablets use (add :<port> if not 80)
LMS_SMOKE_PASSWORD='<demo password>' python3 scripts/smoke_test.py \
    --base-url http://192.168.10.10 --other-class-username demo.class11
```

The smoke test checks login, catalogue, signed playback, `HEAD`/Range 206 at start, middle
and end of a file, denial of unsigned/tampered/extended URLs and non-GET methods, no
directory listing, path traversal, progress save/read, cross-class denial, and logout.

## 9. Install the app on tablets

See [../mobile/README.md](../mobile/README.md). On first launch tap **Server:** on the
sign-in screen and enter `http://192.168.10.10` (or your hostname), then **Test connection**.

## 10. Internet-independence test (AC-04, T-14)

1. Start two lessons on two tablets.
2. Unplug the router's WAN/uplink cable (or disable the WAN interface). Keep the LAN
   switch, AP and LMS host powered.
3. Confirm playback continues, seek works, and you can open another lesson.
4. Sign out and sign in again, and check that progress still saves.
5. Record the results in the test report ([testing-plan.md](testing-plan.md)).

If tablets lose access when WAN is down, the usual causes are: the tablet uses a public
DNS name for the server (use the IP or local DNS), the Wi-Fi network has captive-portal
or "no internet" auto-switching (disable *Switch to mobile data* / *Avoid poor
connections* on the tablet), or the AP's guest/client isolation is on.

## 11. Logs

```bash
docker compose logs --since 1h api                       # API: one line per request with request_id
docker compose logs --since 1h nginx | grep '"type":"media"'   # video requests (status, bytes, range, sid)
docker compose logs --since 1h nginx | grep '"type":"media"' | grep -E '"status":(403|404|410)'   # media problems
```

API request lines include `request_id`, path (no query string), status, duration and the
student ID; the same `request_id` is set on Nginx's proxied request. Media log lines carry
`sid` (student ID) so a student's video sessions can be followed. Passwords, tokens and
URL signatures are not written to the access logs, and Nginx's own error log is kept at
`crit` level for `/media/` so it cannot record signed URLs either. Container logs rotate
at 20 MB × 10 files per service. Treat exported logs as internal: they contain student
IDs and lesson titles.

## 12. Reset prototype data

```bash
docker compose down -v      # DELETES the database volume (students, progress, catalogue)
docker compose up -d
scripts/seed_demo_data.sh
```

Video files in `VIDEO_ROOT` are not touched. Back up first if anything should be kept
([backup-restore.md](backup-restore.md)).

## 13. Run the tests

From the repository root (`cd ..` if you are still in `deploy/`):

```bash
(cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest)
(cd mobile && flutter test && flutter analyze)
```

The end-to-end app test (`mobile/integration_test/app_flow_test.dart`) runs the real app
on an emulator or tablet against a running stack; the header of that file shows the command.

## 14. Load testing (after the prototype demo)

`scripts/load_test.py` simulates 10–100 students streaming at once to measure the server
before any capacity claim (PRD §14.4). It needs load-test accounts and the password in
`LMS_LOAD_PASSWORD`:

```bash
cd deploy
printf '%s\n' "$PW" | scripts/lms-admin.sh create-load-students --count 100 --class "Class 12" --password-stdin
LMS_LOAD_PASSWORD="$PW" python3 scripts/load_test.py --base-url http://192.168.10.10 --clients 25 --duration 120
scripts/lms-admin.sh delete-load-students        # removes the accounts and their progress
```

Run it from a wired machine on the LAN, not on the server. Details, limits and how to read
the output: [testing-plan.md](testing-plan.md#staged-load-test-server-side).

## 15. Upgrade path

1. `scripts/backup.sh`
2. `git pull`
3. `docker compose up -d --build` (migrations apply on start; set `MIGRATE_ON_START=false`
   to run them by hand with `docker compose run --rm api alembic upgrade head`)
4. `scripts/smoke_test.py ...`
5. If something is wrong: check out the previous version, rebuild, and restore the backup.

## 16. Moving the server to another site (pilot at another campus)

Nothing in the database, the videos or the app depends on the old network, except two
settings and the address typed on each tablet. Before you leave:

1. `scripts/backup.sh` and copy the newest dump and config archive to a USB stick.
2. Note the admin accounts (`lmsadmin`, OMV `admin`) and the demo/student passwords.
3. Shut the server down cleanly (OMV → power icon → Shutdown).

At the new site:

1. Connect the server to a **wired** switch port on the network the tablets will use
   (same subnet as the tablets avoids the NAT problem seen in the test report, where every
   tablet appeared as the router's address). Ask that network's admin for a **static address
   or DHCP reservation** so it does not change again.
2. Boot it and find the address: it is printed on the console, or run `ip -4 addr show`
   over SSH if you know it. The OMV UI is at `http://<address>:8081`.
3. Re-point the installation (keeps everything else):

   ```bash
   cd ~/campus-lms/deploy
   scripts/set_network.sh --media-base-url http://<new address> --allow <tablet subnet, e.g. 10.20.0.0/16>
   ```

   It rewrites `MEDIA_BASE_URL`, regenerates `nginx/allowlist.conf`, recreates the API,
   restarts Nginx and runs `check_stack.sh`. Use `--dry-run` first to see the changes.
4. On each tablet: sign-in screen → **Server** → the new address → *Test connection* →
   Save. Or build the APK with the new default (`mobile/README.md`).
5. Run the smoke test from a laptop on the new Wi-Fi: `python3 scripts/smoke_test.py --base-url http://<new address>`.
6. Check the Wi-Fi: tablets must reach the server (no client isolation, no guest VLAN),
   and each tablet should have its own address as seen by the server
   (`docker compose logs nginx | grep remote_addr`). If they all share one address, the
   login throttle is shared by the whole class — fix the routing or raise the limit.

To avoid step 4 at every move, give the server a **local DNS name** (e.g. `lms.campus.lan`)
on each site's DNS server and use that name as `MEDIA_BASE_URL` and in the app; then only
the DNS record changes. Public DNS must not be relied on (FR-10).

## Developing on Windows

Docker Desktop runs the same stack. Use Git Bash for the `.sh` scripts, set
`VIDEO_ROOT=C:/campus-lms/videos` (forward slashes) and `LMS_HTTP_PORT=8080` if port 80
is taken (Windows' HTTP.sys often holds it). An Android emulator reaches the host at
`http://10.0.2.2:8080`.

Use `http://127.0.0.1:8080`, not `http://localhost:8080`, for the smoke test on Windows:
Python tries IPv6 `::1` first for `localhost` and every request then takes ~2 s longer.

Docker Desktop is for development only: it hides client source addresses (every tablet
appears to Nginx as the Docker gateway), so `allowlist.conf`, the per-IP login throttle
and the client IPs in the logs do not work there. The only network control is Windows
Defender Firewall (scope an inbound rule for TCP 8080 to the campus subnets). Run
multi-tablet pilots on a Linux host.

If Docker Desktop shows an error dialog at start-up and the log
(`%LOCALAPPDATA%\Docker\log\host\com.docker.backend.exe.log`) says
`remove …\dockerInference: The file cannot be accessed by the system` (or the same for
`docker-secrets-engine\engine.sock`), stale socket files from an unclean shutdown are
blocking it. Quit Docker Desktop, rename `%LOCALAPPDATA%\Docker\run` and
`%LOCALAPPDATA%\docker-secrets-engine` (e.g. append `.stale-<date>`), and start it again.
The files cannot be deleted directly, but renaming the folder works and Docker recreates it.
