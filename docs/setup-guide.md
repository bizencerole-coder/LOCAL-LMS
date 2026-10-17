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
| `VIDEO_ROOT` | **Host** path of the content library (videos, PDF notes, images in `<batch>/<class>/<subject>/<module>/`); mounted at `/srv/campus-lms/videos`, read-only for Nginx, writable for the API (dashboard uploads) |
| `LMS_CONTENT_UID` / `LMS_CONTENT_GID` | The API runs as this user/group: the owner of `VIDEO_ROOT` (`stat -c '%u %g' "$VIDEO_ROOT"`), so dashboard and network-share files can be edited by both. `install.sh` sets them |
| `MEDIA_BASE_URL` | Fixed base for playback URLs (`http://lms.campus.lan`), recommended on a LAN; empty = the address each tablet typed |
| `PLAYBACK_URL_TTL_SECONDS` | Signed URL lifetime (default 7200). When a URL expires mid-lesson the app fetches a new one and continues |
| `SESSION_TTL_SECONDS` | Sign-in lifetime (default 28800 = 8 h) |
| `COMPLETION_THRESHOLD` | A lesson is complete once the playback position reaches this fraction of its length (default 0.9; seeking counts; 0 = only when the video plays to the end) |
| `LMS_HTTP_BIND` / `LMS_HTTP_PORT` | Where Nginx listens. Binding to the LAN IP keeps other interfaces closed, but does not filter by source |
| `LOG_FORMAT` | `text` or `json` for API logs |
| `STAFF_SESSION_TTL_SECONDS` | Dashboard sign-in lifetime (default 43200 = 12 h) |
| `UPLOAD_MAX_BYTES` | Largest file staff may upload (default 8 GiB; Nginx allows up to 8 GiB) |
| `CONTENT_SHARE_PATH` | How staff PCs reach `VIDEO_ROOT`, shown on dashboard pages, e.g. `'\\192.168.10.10\campus-lms\videos'` |
| `DISPLAY_TIMEZONE` | Time zone for times on the dashboard (default `Asia/Kolkata`) |
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
scripts/make_test_videos.sh /srv/campus-lms/videos            # 5 videos (incl. a 32-min lesson, ~9 min to encode), PDF notes, an image
scripts/make_test_videos.sh /srv/campus-lms/videos --short    # quicker: long lesson cut to 5 min
scripts/seed_demo_data.sh                                     # prompts for the demo password
```

The seed (from `backend/seed/demo_catalog.json`) creates the batch *Batch 2026-27* with
Class 12 (Computer Science › Python Basics: three videos, one a draft, and PDF notes;
Mathematics › Calculus: the long video) and Class 11 (Physics › Motion: a video and an image),
and these students:

| Username | Class | Purpose |
|---|---|---|
| `demo.student`, `demo.student2` | Class 12 | Main demo accounts (two tablets) |
| `demo.class11` | Class 11 | Must not see Class 12 content (AC-07) |
| `demo.inactive` | Class 12 | Inactive account; sign-in is refused (T-03) |

All demo accounts share the password you type; it is never stored in the repository.
Re-running the seed is safe: existing records are left alone. To script it, pipe the
password: `printf '%s\n' "$PW" | scripts/seed_demo_data.sh --password-stdin`.

The demo files use the folder layout of §7 (`batch-2026-27/class12/computer-science/01-python-basics/01-variables-and-types.mp4`
and so on), so what you see in the file share is what the app shows. The seed gives them
their titles; a plain folder sync on the same files would name them from the file names.
Staff accounts are not part of the seed: create one with `scripts/lms-admin.sh create-staff` (§7.1).

## 7. Managing content: the staff dashboard and the folders

Everything the tablets show is organised as **Batch › Class › Subject › Module › Content**:

| Level | Example | Notes |
|---|---|---|
| Batch | Batch 2026-27, NEET 2027 | A group of students for a period. Inactive batches are hidden from their students. |
| Class | Class 12 | Students are assigned to one class. |
| Subject | Computer Science | |
| Module | Python Basics | A unit of a subject (chapter, topic, week…). Hidden modules are not shown. |
| Content | a video, PDF notes, an image | MP4 (H.264 + AAC, fast-start), PDF, JPG/PNG/WebP. Each item is a draft until published. |

Each level is also a folder under `VIDEO_ROOT`, so the network share mirrors the app:

```text
VIDEO_ROOT/
  batch-2026-27/                      → batch "Batch 2026-27"   (title.txt holds the display name)
    class12/                          → class "Class 12"
      computer-science/               → subject "Computer Science"
        01-python-basics/             → module "Python Basics", order 1
          01-variables-and-types.mp4  → video, order 1
          01-variables-and-types.txt  → optional: first line = title, rest = description
          05-python-basics-notes.pdf  → notes (PDF)
        quick-revision.mp4            → no module folder: shown in a module called "General"
  .uploads/  .trash/                  → used by the dashboard (uploads in progress; deleted files, kept 30 days)
```

There are two ways to manage it, and they can be mixed freely: the folder sync keeps the
database and the folders in step.

### 7.1 The staff dashboard (recommended)

Open `http://<server>/admin/` in a browser on a staff PC (typing just `http://<server>/`
also gets there). Create the first administrator on the server, once:

```bash
scripts/lms-admin.sh create-staff --username admin --name "Administrator" --role admin   # asks for a password
```

Administrators create the other staff accounts under **Staff**. *Staff* accounts manage
content and students; *administrator* accounts can also manage staff accounts and delete
students. The dashboard has:

- **Content**: batches → classes → subjects → modules, each created with a name; the folder
  name is made from it (or typed in) and fixed from then on. Renaming changes only the
  display name (and the folder's `title.txt`). Subjects, modules and items can be put in
  order with the arrows; only empty batches, classes, subjects and modules can be deleted.
- **Uploading**: on a module's page, drop files onto the upload area or choose them. Each
  file gets its own **Title** (filled in from the file name; change it) and **Description**
  (optional, shown to students); press **Upload** when they are right. Each file is checked
  (an MP4 must be H.264 + AAC with fast-start; a PDF must be a real PDF), then stored in the
  module's folder under its title, with the title and description in its `.txt` file. Files
  that pass are published straight away when the box is ticked; files with problems stay
  drafts. (The *Module settings* below the upload area rename the module, not the files.)
  Uploads stream to the content disk, so large videos are fine (limit `UPLOAD_MAX_BYTES`,
  default 8 GB, and 1 GB must stay free).
- **Each item's page**: preview (video player, PDF, image), title and description (shown to
  students), publish / unpublish / archive, move to another module of the same class (the
  file moves too; students keep their progress), and delete (the file goes to `.trash` for
  30 days; students' progress on it is removed).
- **Students**: search and filter by class, create a student, edit details, change class,
  reset a password (signs the student out everywhere), deactivate, see what they watched.
  **Import from CSV** creates many students at once (columns `student_code,username,full_name,class,password`;
  an empty password gets a generated one, shown once on the result page).
- **Folder sync**: the result of every sync, and *Sync now*.

The dashboard needs no internet (no external fonts or scripts), works on any modern
browser, and keeps staff signed in for 12 hours (`STAFF_SESSION_TTL_SECONDS`).

### 7.2 Copying files into the folders

From Windows: open `\\<server>\campus-lms` (OMV SMB share; sign in as `lmsadmin`) and copy
into `videos\<batch>\<class>\<subject>\<module>\`. Each batch, class, subject and module
page in the dashboard shows its folder. Set `CONTENT_SHARE_PATH` in `.env` (e.g.
`'\\192.168.10.10\campus-lms\videos'`) to have the dashboard show the full share path.

Rules for names:
- Letters, digits, `.`, `-` and `_` only, **no spaces**; use `title.txt` (in a folder) or
  `<file>.txt` (next to a file) for the names students see, e.g. `Lesson 2: Functions`.
- A leading number and dash (`01-`, `02-`) sets the order and is removed from the name;
  `-` and `_` become spaces, words are capitalised, and `class12` becomes `Class 12`.
- The top folder must be a batch that exists in the dashboard. Folders for new classes,
  subjects and modules may be created by hand; the sync adds them.
- Exactly `<batch>/<class>/<subject>/<file>` or `<batch>/<class>/<subject>/<module>/<file>`.
- A copied video should be checked first (`python3 scripts/inspect_media.py lesson.mp4`):
  a file with problems is registered but stays a draft.

### 7.3 The folder sync

Every 5 minutes cron runs the sync on the server (as `lmsadmin`; *System → Scheduled Tasks* in OMV works too):

```cron
*/5 * * * * cd /home/lmsadmin/campus-lms/deploy && scripts/lms-admin.sh sync-videos --publish --archive-missing >> /srv/backups/lms/sync.log 2>&1
```

It registers new files (published when they pass the check), follows moved and renamed
files, refreshes replaced files and archives items whose files were removed. *Sync now* on
the dashboard does the same at once. By hand:

```bash
scripts/lms-admin.sh sync-videos                     # new files as drafts; review them in the dashboard
scripts/lms-admin.sh sync-videos --publish --archive-missing
scripts/lms-admin.sh tree                            # the whole catalogue with folders and storage keys
```

A file copied in mid-way is registered with the size it had at that moment; the next run
corrects it. Prefer copying into a folder outside `videos/` and moving the finished file in.

| You do this in the share | The next sync does this |
|---|---|
| Rename a file or folder, or move a file to another module or subject | The item keeps its status and every student's progress, moves to the new module, and takes the new order number. A name that came from the file name follows the new name; a title from `<file>.txt`, the dashboard or the seed is kept. (`~ moved` in the log) |
| Move the last file out of a module folder | The empty module disappears; it comes back when a file is placed there again. |
| Replace a file with a new version (same name) | Size and duration are refreshed. (`~ updated`) |
| Delete a file | The item is archived (hidden; progress kept). |
| Delete a file and put two identical copies elsewhere | Treated as a removal and two new items: a move is only recognised when exactly one matching file disappears and one appears (same size, plus same duration for videos or same checksum for notes and images). |

Nothing is archived when the whole library looks missing (no files at all, or more than half
of the items gone at once), so a disk that failed to mount does not hide every lesson. If
items were archived by mistake, publish them again on their pages.

### 7.4 The command line

Every dashboard action also exists in `scripts/lms-admin.sh --help` (run on the server), for
example: `create-batch`, `create-class --batch`, `create-subject --class "Batch 2026-27/Class 12"`,
`create-module --subject "Batch 2026-27/Class 12/Physics" --publish`, `publish-module`,
`add-content --module ... --storage-key ... --title ...`, `publish-content` / `unpublish-content` /
`archive-content`, `create-student`, `set-password`, `assign-class`, `activate-student` /
`deactivate-student`, `list-students`, `create-staff`, `set-staff-password`, `activate-staff` /
`deactivate-staff`, `list-staff`, `check-media [--update]`, `scan-videos`, `purge-sessions`,
`seed-demo`. The older names (`create-chapter`, `add-video`, `publish-video`, …) still work.
Passwords are always prompted for (or read with `--password-stdin`), never passed as arguments.

**File permissions.** The API writes in `VIDEO_ROOT` (uploads, moves, deletes) as
`LMS_CONTENT_UID:LMS_CONTENT_GID`, which must be the owner of the content folder, the same
account the network share writes as (`lmsadmin` on OMV). `install.sh` sets them; check with
`stat -c '%u %g' "$VIDEO_ROOT"`. If they do not match, the dashboard shows *The server cannot
change files in …* and uploads fail with that message.

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

Content files in `VIDEO_ROOT` are not touched (re-register them with the folder sync, §7.3). Back up first if anything should be kept
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

One command, as the operator account on the server:

```bash
deploy/scripts/upgrade.sh          # add --share-path '\\<server>\campus-lms\videos' to show the share on the dashboard
```

It backs up the database and configuration, pauses the folder-sync cron line, adds settings
newer versions need to `.env` (never changing existing values), runs `git pull --ff-only`
and `docker compose up -d --build` (migrations apply on start; set `MIGRATE_ON_START=false`
to run them by hand with `docker compose run --rm api alembic upgrade head`), restarts Nginx,
waits until everything is healthy, runs `scripts/check_stack.sh`, and resumes the cron line.
Then run the smoke test (§8). If something is wrong: check out the previous version,
rebuild, and restore the backup ([backup-restore.md](backup-restore.md)).

**Upgrading to batches, modules and the staff dashboard (October 2026).** This upgrade
restructures the catalogue; nothing is lost and students keep their progress:

- The database migration creates one batch for the current academic year (for example
  *Batch 2026-27*, folder `batch-2026-27`) holding every existing class, renames chapters to
  modules and videos to content items (same IDs), and prefixes every storage key with the
  batch folder.
- When the API starts it moves the existing `<class>/…` folders into `<batch folder>/…` to
  match (`python -m app.cli relocate-content` shows what would move). A folder sync started
  meanwhile waits for it.
- The API now writes in `VIDEO_ROOT` as `LMS_CONTENT_UID:LMS_CONTENT_GID`, the owner of
  `VIDEO_ROOT` (§4); `upgrade.sh` adds them to `.env` from the folder's owner.
- `upgrade.sh` pauses the 5-minute sync cron job while upgrading and resumes it afterwards.
- Create the first dashboard administrator (§7.1).
- Install app 1.1 on the tablets for modules, notes and images. App 1.0 keeps working (it
  shows the videos of each module) until the tablets are updated.

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
