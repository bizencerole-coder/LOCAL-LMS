# Campus LMS — framed prototype

Local campus learning platform. Staff organise content in a web dashboard as
**Batch › Class › Subject › Module › Content** (videos, PDF notes, images); students on
Android tablets sign in, see their class's subjects and modules, stream recorded lessons and
read notes from a server on the campus LAN. Nothing in the core path needs the public internet.

Requirements: [docs/PRD.md](docs/PRD.md) (v1.0, 15 Oct 2026).

```
Tablet (Flutter)  ──HTTP──▶  Nginx :80 ──▶ /api/*    ──▶ FastAPI ──▶ PostgreSQL
Staff browser     ──HTTP──▶            ──▶ /admin/*  ──┘    │
                                       └──▶ /media/* ──▶ VIDEO_ROOT ◀── uploads, folder sync
Staff PC (SMB share) ──────────────────────────────────────┘    <batch>/<class>/<subject>/<module>/
```

The API authorizes an item and returns a short-lived **signed URL**; the tablet then
streams the video (HTTP Range/206 for seeking) or downloads the notes directly from Nginx.
File bytes never pass through the API. The folders under `VIDEO_ROOT` mirror the catalogue,
so staff can upload in the dashboard or copy files into the network share; a sync every
5 minutes keeps both in step. See [docs/architecture.md](docs/architecture.md).

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI app (`app/`: student API, staff dashboard in `app/admin/`, folder sync), Alembic migrations, admin CLI, demo seed manifest, tests |
| `mobile/` | Flutter Android app (student UI, video player, notes and image viewers) |
| `deploy/` | `compose.yaml`, `.env.example`, Nginx config, `install.sh`, `scripts/set_network.sh` (site move), operator scripts |
| `docs/` | PRD, setup, architecture, API, testing, troubleshooting, backup/restore, M0 inventory |
| `sample-data/` | How the demo test files are generated |

## Quick install (fresh Linux host)

```bash
deploy/install.sh --dry-run                                   # show what would be done; changes nothing
deploy/install.sh --allow 192.168.10.0/24 --firewall --demo   # Docker, folders, .env, access control, stack, demo data
```

One command for a fresh Debian 12/13, Ubuntu 24.04 or OpenMediaVault 7/8 host, run as the
sudo-capable operator account (setup guide sections 2–6 and 8). `--video-root` points it at an
OMV shared folder, `--media-base-url` sets a local DNS name, `--help` lists the rest. It creates
folders only and never touches disks; it can be re-run, and replaces an existing `.env` or
allowlist only with `--force`. The manual steps below and in
[docs/setup-guide.md](docs/setup-guide.md) remain the reference.

## Quick start (any Linux host or Docker Desktop)

```bash
cd deploy
cp .env.example .env            # set POSTGRES_PASSWORD, MEDIA_SIGNING_SECRET, VIDEO_ROOT
scripts/make_test_videos.sh "$(grep ^VIDEO_ROOT= .env | cut -d= -f2)" --short
docker compose up -d --build
scripts/seed_demo_data.sh        # prompts for the demo students' password
scripts/lms-admin.sh create-staff --username admin --name "Administrator" --role admin   # dashboard account
scripts/check_stack.sh           # every layer, with the address Nginx publishes
LMS_SMOKE_PASSWORD='<that password>' python3 scripts/smoke_test.py \
    --base-url http://127.0.0.1 --other-class-username demo.class11   # add :<LMS_HTTP_PORT> if not 80
```

Then open `http://<server>/admin/` in a browser to manage content and students, install the
app on a tablet ([mobile/README.md](mobile/README.md)), set the server address on the
sign-in screen, and sign in as `demo.student`.

Full instructions, including OMV integration and the WAN-disconnect test:
[docs/setup-guide.md](docs/setup-guide.md).

## Development

```bash
# From the repository root. Backend tests use SQLite (no Docker needed).
(cd backend && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt && .venv/bin/python -m pytest)
# Windows: .venv/Scripts/pip and .venv/Scripts/python

# Flutter tests and static analysis
(cd mobile && flutter test && flutter analyze)

# End-to-end app test on an emulator against a running stack (see mobile/integration_test/)
```

## Status against the PRD

Implemented in this repository (M1–M4 software, plus the staff dashboard of §20 F3): local
login with argon2 hashes and revocable sessions; batch › class › subject › module › content
catalogue scoped to the student's class; videos, PDF notes and images behind signed,
expiring Nginx URLs with Range support; progress upsert with configurable completion;
health/readiness endpoints; request-ID logging; a staff web dashboard (content tree with
uploads, publish/unpublish/archive, moves and deletes that keep the folders in step,
students with CSV import, staff accounts with admin/staff roles, folder-sync reports,
notices, home-page banners and the school's name, colour and logo);
a folder sync that builds and follows the catalogue from `batch/class/subject/module/file`;
an admin CLI with the same operations; and the Flutter app (1.2) in the school's branding:
sign-in, a header with notices and connection status, side menu and bottom bar, a home page
with greeting, banner slides, notices, Continue Watching and subjects with progress, Subjects,
My Learning, Notices and Profile tabs, subject and module pages, a player with seek, ±10 s,
speed, full-screen, resume and retry, and notes/image viewers.

Verified on the development machine (Docker stack, smoke test, emulator end-to-end run,
backup/restore): [docs/test-report-2026-10-16.md](docs/test-report-2026-10-16.md).

Still to do on site (cannot be done from the repository): M0 hardware/network inventory
([docs/m0-inventory.md](docs/m0-inventory.md)), choosing the host (reuse OMV or fresh
server), and the physical-tablet tests in [docs/testing-plan.md](docs/testing-plan.md)
(two tablets, WAN disconnected, 30-minute run). **No 500-viewer capacity is claimed** — that
needs the staged load tests in PRD §14.4.

Known limitations: [docs/architecture.md#known-limitations](docs/architecture.md#known-limitations).
