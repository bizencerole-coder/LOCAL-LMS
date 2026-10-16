#!/usr/bin/env bash
# Back up the database and configuration (not the video library; back that up
# separately, e.g. with OMV rsync jobs).
#
#   deploy/scripts/backup.sh                 # writes to deploy/backups/
#   BACKUP_DIR=/srv/backups/lms deploy/scripts/backup.sh
#   KEEP=14 deploy/scripts/backup.sh         # keep the newest 14 of each kind
#
# The config archive contains deploy/.env (secrets): keep backups on restricted storage.
set -euo pipefail
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-./backups}"
KEEP="${KEEP:-30}"
case "$KEEP" in
    ''|*[!0-9]*|0) echo "KEEP must be a positive integer (got '$KEEP')" >&2; exit 1 ;;
esac
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
mkdir -p "$BACKUP_DIR"

DB_FILE="$BACKUP_DIR/campus_lms_db_$STAMP.dump"
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$DB_FILE.part"
mv "$DB_FILE.part" "$DB_FILE"
echo "database -> $DB_FILE ($(du -h "$DB_FILE" | cut -f1))"

CONFIG_FILE="$BACKUP_DIR/campus_lms_config_$STAMP.tar.gz"
# The shell opens the archive, so tar never sees the path (GNU tar would read a Windows
# "C:/..." path as a remote host).
tar -cf - .env compose.yaml nginx | gzip > "$CONFIG_FILE.part"
mv "$CONFIG_FILE.part" "$CONFIG_FILE"
echo "config   -> $CONFIG_FILE"

# Retention: keep the newest KEEP of each kind. NUL-delimited, so paths with spaces work.
for pattern in 'campus_lms_db_*.dump' 'campus_lms_config_*.tar.gz'; do
    find "$BACKUP_DIR" -maxdepth 1 -name "$pattern" -print0 \
        | sort -rz | tail -zn +"$((KEEP + 1))" | xargs -0r rm -f --
done
