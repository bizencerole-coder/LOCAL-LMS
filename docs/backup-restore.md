# Backup and restore

What needs protecting, and how:

| Data | Where | Backed up by |
|---|---|---|
| Students, catalogue, progress, sessions | PostgreSQL volume `campus-lms_pgdata` | `deploy/scripts/backup.sh` (`pg_dump`) |
| Configuration and secrets | `deploy/.env`, `deploy/compose.yaml`, `deploy/nginx/` | `backup.sh` (tar archive) |
| Video library | `VIDEO_ROOT` | **Separately** — OMV rsync/rsnapshot job or copy to another disk. Keep untouched source files too (PRD §12.2) |

## Back up

```bash
cd deploy
scripts/backup.sh                          # -> deploy/backups/campus_lms_db_<UTC>.dump + config archive
BACKUP_DIR=/srv/backups/lms KEEP=14 scripts/backup.sh
```

The config archive contains `.env` (secrets): store backups on restricted storage
(`backup.sh` creates them with mode 600), not on a student-accessible share.

Schedule daily with cron as the operator account (a member of the `docker` group).
First create the backup directory once, owned by that account (on OMV, put it on the data
disk rather than the system disk):

```bash
sudo install -d -m 700 -o "$USER" -g "$USER" /srv/backups/lms
```

Then add the job with `crontab -e`, using the real path of your checkout and a log file
inside the backup directory (the account cannot write to `/var/log`):

```cron
30 18 * * * cd /home/lmsadmin/campus-lms/deploy && BACKUP_DIR=/srv/backups/lms scripts/backup.sh >> /srv/backups/lms/backup.log 2>&1
```

Check `backup.log` and the newest dump's timestamp after the first night.

Copy backups off the LMS host (another disk or machine) — a backup on the same disk does
not survive a disk failure.

## Restore

```bash
cd deploy
scripts/restore.sh backups/campus_lms_db_20261015T183000Z.dump
```

The script asks you to type `RESTORE`, writes a safety backup of the current database
to `backups/pre-restore/`, stops the API and Nginx, restores the dump into a scratch
database in a single transaction, and only then swaps it in for the live one. If the
restore fails, the live database is untouched; the API and Nginx are started again
either way.

To restore configuration, from `deploy/`:

```bash
tar -xzf backups/campus_lms_config_<UTC>.tar.gz -C .
docker compose up -d --force-recreate nginx api   # Nginx re-renders its config only when recreated
```

## Test the backup

At least once before the demo, and after any upgrade:

1. `scripts/backup.sh`
2. Note a student's saved position on one lesson.
3. Save a different position, then `scripts/restore.sh <the dump from step 1>`.
4. Confirm the position from step 2 is back.

## Full rebuild on a new host

1. Install Docker, copy the repository, restore `deploy/.env` from the config archive.
2. Restore or copy the video library to the new `VIDEO_ROOT`.
3. `docker compose up -d --build` (creates an empty, migrated database).
4. `scripts/restore.sh <latest dump>`.
5. `scripts/smoke_test.py --base-url http://<new-ip> …`
