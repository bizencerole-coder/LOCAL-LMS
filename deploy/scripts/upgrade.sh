#!/usr/bin/env bash
# Upgrade the LMS on this host to the newest version in git, safely. Run from anywhere as
# the operator account (lmsadmin on the OMV host):
#
#   deploy/scripts/upgrade.sh              # backup, pause the sync, pull, rebuild, check, resume
#   deploy/scripts/upgrade.sh --no-pull    # rebuild what is checked out now
#   deploy/scripts/upgrade.sh --share-path '\\192.168.10.10\campus-lms\videos'
#
# 1. Backs up the database and configuration (scripts/backup.sh; BACKUP_DIR from the
#    environment, else /srv/backups/lms when that folder exists, else deploy/backups).
# 2. Pauses the folder-sync line in this account's crontab (put back at the end, also
#    when a step fails).
# 3. Adds settings newer versions need to deploy/.env; existing values are never changed:
#    LMS_CONTENT_UID / LMS_CONTENT_GID (owner of VIDEO_ROOT, so the API may write there),
#    CONTENT_SHARE_PATH (only with --share-path).
# 4. git pull --ff-only (unless --no-pull).
# 5. docker compose up -d --build: database migrations run on start (the batches upgrade
#    also moves the content folders into the batch folder); Nginx is restarted for its new
#    configuration; waits until every container is healthy.
# 6. scripts/check_stack.sh.
#
# Undo: check out the previous commit, docker compose up -d --build, and restore the backup
# (docs/backup-restore.md).
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
cd "$(dirname "$0")/.."
DEPLOY_DIR="$(pwd)"

PULL=true
SHARE_PATH=""
while [ $# -gt 0 ]; do
    case "$1" in
        --no-pull) PULL=false ;;
        --share-path) SHARE_PATH="${2:?--share-path needs a value}"; shift ;;
        --share-path=*) SHARE_PATH="${1#*=}" ;;
        -h|--help) sed -n '2,27p' "$0"; exit 0 ;;
        *) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
    shift
done

say() { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
env_get() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r"'"'" || true; }

[ -f .env ] || { say "deploy/.env not found; this host is not set up (see deploy/install.sh)." >&2; exit 1; }
docker compose ps >/dev/null 2>&1 || { say "docker compose does not work for this account (docker group?)." >&2; exit 1; }

# --- 1. backup
step "1/6 Backup"
if [ -z "${BACKUP_DIR:-}" ]; then
    if [ -d /srv/backups/lms ]; then BACKUP_DIR=/srv/backups/lms; else BACKUP_DIR="$DEPLOY_DIR/backups"; fi
fi
BACKUP_DIR="$BACKUP_DIR" scripts/backup.sh
say "backup written to $BACKUP_DIR"

# --- 2. pause the folder sync
step "2/6 Pause the folder sync"
MARK="#LMS-UPGRADE-PAUSED# "
CRON_PAUSED=false
# Comment out the folder-sync line(s) with a marker that resume_cron removes again.
pause_sync_line() { sed -E 's@^([^#].*sync-(videos|content).*)$@'"$MARK"'\1@'; }
resume_cron() {
    if $CRON_PAUSED; then
        crontab -l 2>/dev/null | sed "s|^$MARK||" | crontab - && say "folder sync resumed (crontab)"
        CRON_PAUSED=false
    fi
}
trap resume_cron EXIT
if command -v crontab >/dev/null 2>&1 && crontab -l 2>/dev/null | grep -qE '^[^#].*sync-(videos|content)'; then
    crontab -l | pause_sync_line | crontab -
    CRON_PAUSED=true
    say "folder sync paused in this account's crontab (it is put back at the end)"
else
    say "no folder-sync line in this account's crontab; nothing to pause"
fi

# --- 3. settings
step "3/6 Settings (deploy/.env)"
VIDEO_ROOT="$(env_get VIDEO_ROOT)"
add_setting() {   # add_setting NAME VALUE: appended only when NAME is not set yet
    if [ -n "$(env_get "$1")" ]; then
        say "keep   $1=$(env_get "$1")"
    else
        printf '%s=%s\n' "$1" "$2" >> .env
        say "added  $1=$2"
    fi
}
if [ -n "$VIDEO_ROOT" ] && [ -d "$VIDEO_ROOT" ]; then
    add_setting LMS_CONTENT_UID "$(stat -c %u "$VIDEO_ROOT")"
    add_setting LMS_CONTENT_GID "$(stat -c %g "$VIDEO_ROOT")"
else
    say "WARNING: VIDEO_ROOT '$VIDEO_ROOT' is not a folder here; set LMS_CONTENT_UID/GID by hand"
fi
if [ -n "$SHARE_PATH" ]; then
    add_setting CONTENT_SHARE_PATH "'$SHARE_PATH'"
fi

# --- 4. code
step "4/6 Code"
if $PULL; then
    before="$(git rev-parse --short HEAD)"
    git pull --ff-only
    say "updated $before -> $(git rev-parse --short HEAD)"
else
    say "not pulling (--no-pull); building $(git rev-parse --short HEAD 2>/dev/null || echo 'this checkout')"
fi

# --- 5. rebuild and restart
step "5/6 Rebuild and restart"
docker compose up -d --build
# Nginx reads its configuration (and resolves the API) when it starts.
docker compose restart nginx
healthy=false
for _ in $(seq 1 60); do
    statuses="$(docker compose ps --format '{{.Service}} {{.Status}}' 2>/dev/null)"
    if [ "$(printf '%s\n' "$statuses" | grep -c '(healthy)')" -ge 3 ]; then healthy=true; break; fi
    sleep 5
done
printf '%s\n' "$statuses"
if ! $healthy; then
    say "WARNING: not every container became healthy within 5 minutes; see: docker compose logs api nginx"
fi
say "-- what the API did on start (migrations, folder moves):"
docker compose logs api --since 10m 2>/dev/null | grep -E "Running upgrade|^api-1  \| (would )?move |WARNING|ERROR" | tail -20 || true

# --- 6. check
step "6/6 Check"
if scripts/check_stack.sh; then
    say ""
    say "UPGRADE COMPLETE"
else
    say ""
    say "UPGRADE FINISHED WITH PROBLEMS: see the FAIL lines above and docs/troubleshooting.md"
    exit 1
fi
