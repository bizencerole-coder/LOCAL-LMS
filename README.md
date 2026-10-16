# Campus LMS — framed prototype

Local campus video-learning platform: students on Android tablets sign in, browse
their class's subjects → chapters → lessons, and stream recorded lessons from a
server on the campus LAN. Nothing in the core path needs the public internet.

Requirements: [docs/PRD.md](docs/PRD.md) (v1.0, 15 Oct 2026).

```
Tablet (Flutter)  ──HTTP──▶  Nginx :80 ──▶ /api/*   ──▶ FastAPI ──▶ PostgreSQL
                                     └──▶ /media/* ──▶ MP4 files (VIDEO_ROOT, read-only)
```

The API authorizes a lesson and returns a short-lived **signed URL**; the player then
streams the MP4 directly from Nginx (HTTP Range/206 for seeking). Video bytes never pass
through the API. See [docs/architecture.md](docs/architecture.md).

## Repository layout

| Path | Contents |
|---|---|
| `backend/` | FastAPI app (`app/`), Alembic migrations, admin CLI, demo seed manifest, tests |
| `mobile/` | Flutter Android app (student UI and player) |
| `deploy/` | `compose.yaml`, `.env.example`, Nginx config, operator scripts |
| `docs/` | PRD, setup, architecture, API, testing, troubleshooting, backup/restore, M0 inventory |
| `sample-data/` | How the demo test videos are generated |

## Quick start (any Linux host or Docker Desktop)

```bash
cd deploy
cp .env.example .env            # set POSTGRES_PASSWORD, MEDIA_SIGNING_SECRET, VIDEO_ROOT
scripts/make_test_videos.sh "$(grep ^VIDEO_ROOT= .env | cut -d= -f2)" --short
docker compose up -d --build
scripts/seed_demo_data.sh        # prompts for the demo students' password
scripts/check_stack.sh           # every layer, with the address Nginx publishes
LMS_SMOKE_PASSWORD='<that password>' python3 scripts/smoke_test.py \
    --base-url http://127.0.0.1 --other-class-username demo.class11   # add :<LMS_HTTP_PORT> if not 80
```

Then install the app on a tablet ([mobile/README.md](mobile/README.md)), set the server
address on the sign-in screen, and sign in as `demo.student`.

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

Implemented in this repository (M1–M4 software): local login with argon2 hashes and
revocable sessions; class-scoped catalogue; signed, expiring Nginx playback URLs with Range
support; progress upsert with configurable completion; health/readiness endpoints;
request-ID logging; admin CLI (classes, subjects, chapters, students, video import,
publish/unpublish, media checks); Flutter app with login, home, Continue Watching,
My Learning, chapters, lessons, and a player with seek, ±10 s, speed, full-screen,
resume and retry.

Verified on the development machine (Docker stack, smoke test, emulator end-to-end run,
backup/restore): [docs/test-report-2026-10-16.md](docs/test-report-2026-10-16.md).

Still to do on site (cannot be done from the repository): M0 hardware/network inventory
([docs/m0-inventory.md](docs/m0-inventory.md)), choosing the host (reuse OMV or fresh
server), and the physical-tablet tests in [docs/testing-plan.md](docs/testing-plan.md)
(two tablets, WAN disconnected, 30-minute run). **No 500-viewer capacity is claimed** — that
needs the staged load tests in PRD §14.4.

Known limitations: [docs/architecture.md#known-limitations](docs/architecture.md#known-limitations).
