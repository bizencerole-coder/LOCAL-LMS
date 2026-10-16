#!/usr/bin/env bash
# Restore the database from a backup.sh dump. REPLACES all current LMS data
# (students, catalogue, progress, sessions).
#
#   cd deploy && scripts/restore.sh backups/campus_lms_db_20261015T120000Z.dump
#   deploy/scripts/restore.sh deploy/backups/campus_lms_db_20261015T120000Z.dump   # from the repo root
#
# The dump is restored into a scratch database first and swapped in only if that
# succeeds, so a failed restore leaves the live database untouched. A safety backup
# of the current database is written to backups/pre-restore/ first.
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'

DUMP_ARG="${1:?usage: $0 DUMP_FILE}"
[ -f "$DUMP_ARG" ] || { echo "No such file: $DUMP_ARG" >&2; exit 1; }
# Resolve against the caller's directory before changing into deploy/.
DUMP="$(cd "$(dirname "$DUMP_ARG")" && pwd)/$(basename "$DUMP_ARG")"
cd "$(dirname "$0")/.."

echo "This replaces ALL data in the LMS database with the contents of:"
echo "  $DUMP"
read -r -p "Type RESTORE to continue: " answer
[ "$answer" = "RESTORE" ] || { echo "Cancelled."; exit 1; }

# Hold the dump open: the safety backup's retention pruning can never remove it from under us.
exec 3<"$DUMP"

SAFETY_DIR="${BACKUP_DIR:-./backups}/pre-restore"
echo "Taking a safety backup of the current database into $SAFETY_DIR ..."
BACKUP_DIR="$SAFETY_DIR" "$(pwd)/scripts/backup.sh"

restart_services() { docker compose start api nginx >/dev/null 2>&1 || true; }
on_exit() {
    rc=$?
    restart_services
    if [ $rc -ne 0 ]; then
        echo "Restore FAILED (exit $rc). The live database was not changed." >&2
        echo "Safety backup: $SAFETY_DIR" >&2
    fi
}
trap on_exit EXIT

docker compose stop nginx api

# 1. Restore into a scratch database (single transaction: all or nothing).
docker compose exec -T db sh -c 'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS \"${POSTGRES_DB}_restore\"" \
    -c "CREATE DATABASE \"${POSTGRES_DB}_restore\" OWNER \"$POSTGRES_USER\""'
docker compose exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d "${POSTGRES_DB}_restore" --no-owner --single-transaction' <&3

# 2. Swap it in. Nothing is connected to the live database while api/nginx are stopped.
docker compose exec -T db sh -c 'psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \
    -c "DROP DATABASE \"$POSTGRES_DB\"" \
    -c "ALTER DATABASE \"${POSTGRES_DB}_restore\" RENAME TO \"$POSTGRES_DB\""'

echo "Restore complete."
