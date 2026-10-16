#!/usr/bin/env bash
# Run the admin CLI inside the API container. Examples:
#   deploy/scripts/lms-admin.sh tree
#   deploy/scripts/lms-admin.sh sync-videos --publish     # register files copied into the video folders
#   deploy/scripts/lms-admin.sh scan-videos
#   deploy/scripts/lms-admin.sh publish-video class12/computer-science/lesson-04.mp4
#   printf '%s\n' "$PW" | deploy/scripts/lms-admin.sh create-student ... --password-stdin
#   deploy/scripts/lms-admin.sh --help
set -euo pipefail
# Git Bash on Windows would otherwise rewrite container paths such as /app/seed/x.json.
export MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'
cd "$(dirname "$0")/.."
# Keep the terminal for password prompts; drop it when stdin is a pipe (--password-stdin).
if [ -t 0 ]; then
    exec docker compose exec api python -m app.cli "$@"
else
    exec docker compose exec -T api python -m app.cli "$@"
fi
